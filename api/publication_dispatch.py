"""Staged, isolated-test-only SQL/file coordinator. No worker or HTTP route.

The connection factory is trusted configuration, never a request field. Main
validation and production databases are refused. File observations must come
from WindowsPublicationFiles for native evidence, not from a model or caller.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import re
from uuid import UUID

from api.local_publication import (
    AuthorizationDenied, PublicationError, TargetConflict, UnsafeTarget,
)


class DispatchUncertain(RuntimeError):
    """A committed claim or installed file may exist. Never blindly retry."""


class DispatchBindingError(ValueError):
    pass


def canonical_uuid(value):
    if not isinstance(value, str):
        raise DispatchBindingError('Canonical UUID required')
    try:
        valid = str(UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise DispatchBindingError('Canonical UUID required')
    return value


class _Transaction:
    def __init__(self, connection):
        self._connection = connection

    def state(self, action):
        value = self._connection.execute(
            'SELECT retail.api_publication_state_v1(%s)', (action,)).fetchone()[0]
        return json.loads(value) if value is not None else None

    def claim(self, action, mode, key):
        return json.loads(self._connection.execute(
            'SELECT retail.api_claim_publication_v1(%s,%s,%s)',
            (action, mode, key)).fetchone()[0])

    def authorize(self, action, lease):
        return self._connection.execute(
            'SELECT retail.api_authorize_publication_v1(%s,%s)',
            (action, lease)).fetchone()[0] is True

    def observe(self, action, lease, result, digest=None, size=None):
        return json.loads(self._connection.execute(
            'SELECT retail.api_observe_publication_v1(%s,%s,%s,%s,%s)',
            (action, lease, result, digest, size)).fetchone()[0])


class IsolatedPublicationStore:
    def __init__(self, connection_factory, database):
        if not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}', database):
            raise DispatchBindingError('Isolated dispatch test database required')
        self._factory = connection_factory
        self._database = database

    @contextmanager
    def transaction(self):
        connection = None
        try:
            connection = self._factory()
            if connection.autocommit is not False:
                raise DispatchBindingError('Non-autocommit connection required for held locks')
            if connection.execute('SELECT current_database()').fetchone()[0] != self._database:
                raise DispatchBindingError('Database identity mismatch')
            connection.rollback()
            connection.read_only = False
            yield _Transaction(connection)
            connection.commit()
        except BaseException as error:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            if isinstance(error, (DispatchBindingError, KeyboardInterrupt, SystemExit)):
                raise
            # Never include a DSN, SQL error, content or driver traceback.
            raise DispatchUncertain('Inspect durable state and reconcile before retry') from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


class IsolatedPublicationDispatcher:
    """One explicit reconcile/write step. No polling, retries or activation.

    Claim commits first. A second transaction holds owner/case/action locks
    across file checks, both fresh authorizations, installation and receipt.
    Lease/deadline are checked by PostgreSQL, never a caller/host clock.
    """
    def __init__(self, store, files):
        self._store = store
        self._files = files

    def step(self, action, mode, key, checkpoint=None):
        canonical_uuid(action)
        if mode not in ('reconcile', 'write') or not isinstance(key, str) or not re.fullmatch(
                r'[A-Za-z0-9_-]{8,128}', key):
            raise DispatchBindingError('Fixed mode and bounded claim key required')
        with self._store.transaction() as tx:
            claim = tx.claim(action, mode, key)
        if checkpoint:
            checkpoint('claim_committed')
        if claim.get('lease_active') is not True:
            return self._safe_result(claim, None)
        case, content, digest, size, lease = self._binding(claim, action, mode)
        with self._store.transaction() as tx:
            # This acquires the same locks even for read-only reconciliation.
            allowed = tx.authorize(action, lease)
            current = tx.state(action)
            if not current or any(current.get(k) != claim.get(k) for k in (
                    'action_id', 'case_id', 'revision', 'target_id', 'relative_path',
                    'content_sha256', 'content_bytes', 'lease_id', 'mode')) \
                    or current.get('lease_active') is not True or current.get('state') != 'in_progress':
                raise DispatchBindingError('Current bound lease required')
            try:
                if mode == 'reconcile':
                    observed = self._files.reconcile(case, content, digest)
                    if observed not in ('matching', 'missing'):
                        observed = 'unknown'
                else:
                    if not allowed:
                        raise AuthorizationDenied('Fresh authorization required')
                    outcome = self._files.publish(case, content, digest,
                        lambda: tx.authorize(action, lease), checkpoint=checkpoint)
                    observed = 'matching' if outcome in ('created', 'reconciled') else 'unknown'
            except (TargetConflict, UnsafeTarget):
                observed = 'ambiguous'
            except PublicationError:
                observed = 'unknown'
            result = tx.observe(action, lease, observed,
                digest if observed == 'matching' else None,
                size if observed == 'matching' else None)
            if checkpoint:
                checkpoint('receipt_pending')
        if checkpoint:
            checkpoint('receipt_committed')
        return self._safe_result(result, observed)

    @staticmethod
    def _safe_result(state, observation):
        return {'action_id': state.get('action_id'), 'state': state.get('state'),
            'sequence': state.get('sequence'), 'write_attempts': state.get('write_attempts'),
            'observation': observation, 'dispatch_enabled': False}

    @staticmethod
    def _binding(claim, action, mode):
        case = canonical_uuid(claim.get('case_id'))
        lease = canonical_uuid(claim.get('lease_id'))
        content = claim.get('content_text')
        digest = claim.get('content_sha256')
        size = claim.get('content_bytes')
        if claim.get('action_id') != action or claim.get('mode') != mode \
                or type(claim.get('revision')) is not int or claim['revision'] != 1 \
                or claim.get('target_id') != 'local-approved-report-json-v1' \
                or claim.get('relative_path') != f'reports/approved/v1/{case}/revision-1.json' \
                or not isinstance(content, str) or type(size) is not int or not 1 <= size <= 131072 \
                or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise DispatchBindingError('Exact fixed publication binding required')
        try:
            content = content.encode('utf-8')
        except UnicodeError:
            raise DispatchBindingError('Exact UTF-8 content required') from None
        if len(content) != size or sha256(content).hexdigest() != digest:
            raise DispatchBindingError('Exact content hash and byte count required')
        return case, content, digest, size, lease
