"""Isolated new-target SQL adapter and GET-only ASGI surface. Not installed by main.

Only trusted configuration selects a connection/login/database. No NTFS calls,
worker, automatic retries, owner impersonation or runtime activation.
"""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
import threading
from uuid import UUID

import psycopg
from fastapi import HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from api.portal import HEADERS, HEX, PortalGuard

TARGET = 'local-owner-portal-report-v2'


class PortalOutcomeUncertain(RuntimeError):
    """Commit acknowledgement failed; reconcile original identity, never rekey."""


class IsolatedPortalPublicationStore:
    def __init__(self, factory, database, login):
        if not isinstance(database, str) or not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}', database):
            raise ValueError('Isolated database required')
        if not isinstance(login, str) or not re.fullmatch(r'raa_wp4_(?:portal|dispatch)_test_[a-f0-9]{12}', login):
            raise ValueError('Generated restricted login required')
        self.factory, self.database, self.login = factory, database, login
        self.slot = threading.BoundedSemaphore(1)

    def _query(self, sql, args, write=False, validate=None, locks=False):
        if not self.slot.acquire(blocking=False):
            raise HTTPException(429, 'Portal is busy', headers={'Retry-After': '5'})
        conn = None
        committing = False
        try:
            conn = self.factory()
            if conn.autocommit is not False:
                raise HTTPException(503, 'Publication access unavailable')
            if conn.execute('SELECT current_user,current_database()').fetchone() != (self.login, self.database):
                raise HTTPException(503, 'Publication access unavailable')
            conn.rollback()
            # Owner read functions hold SHARE locks through their fresh check.
            # PostgreSQL forbids row locks in read-only transactions; the read
            # login still has no table/write-function privileges.
            conn.read_only = not (write or locks)
            conn.execute("SET LOCAL statement_timeout='5s'")
            conn.execute("SET LOCAL lock_timeout='1s'")
            conn.execute("SET LOCAL timezone='UTC'")
            raw = conn.execute(sql, args).fetchone()[0]
            value = json.loads(raw) if isinstance(raw, str) else raw
            if validate:
                validate(value)
            committing = True
            conn.commit()
            return value
        except BaseException as error:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            if committing and write:
                raise PortalOutcomeUncertain('Reconcile the original action before retry') from None
            if isinstance(error, HTTPException):
                raise
            if isinstance(error, psycopg.errors.InsufficientPrivilege):
                raise HTTPException(401, 'Unauthorized') from None
            if isinstance(error, (psycopg.errors.LockNotAvailable, psycopg.errors.ProgramLimitExceeded)):
                raise HTTPException(429, 'Portal is busy', headers={'Retry-After': '5'}) from None
            if isinstance(error, (psycopg.errors.ObjectNotInPrerequisiteState, psycopg.errors.UniqueViolation)):
                raise HTTPException(409, 'Publication binding conflicts') from None
            if isinstance(error, psycopg.errors.NoDataFound):
                raise HTTPException(404, 'Publication object not found') from None
            if isinstance(error, psycopg.errors.InvalidParameterValue):
                raise HTTPException(422, 'Invalid exact binding') from None
            raise HTTPException(503, 'Publication access unavailable') from None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            self.slot.release()

    def identity(self, session):
        value = self._query('SELECT retail.api_portal_identity_v1(%s)', (session,))
        if value is None:
            raise HTTPException(401, 'Unauthorized')
        return UUID(str(value))

    @staticmethod
    def _id(value):
        try:
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError()
            return value
        except (ValueError, AttributeError):
            raise HTTPException(422, 'Canonical identity required') from None

    @staticmethod
    def _session(value):
        if not isinstance(value, str) or not HEX.fullmatch(value):
            raise HTTPException(401, 'Unauthorized')
        return value

    @staticmethod
    def request_binding(value):
        try:
            request = value['request']
            canonical = value['canonical_payload_text']
            if json.loads(canonical) != request or not HEX.fullmatch(value['request_sha256']) \
                    or sha256(canonical.encode('utf-8')).hexdigest() != value['request_sha256'] \
                    or request['contract_version'] != 'owner-portal-approval-request-v3' \
                    or request['publication_semantics'] != 'guarded-server-acceptance-v1' \
                    or request['review_policy_version'] != 'owner-portal-acceptance-v2' \
                    or type(request['report_revision']) is not int or request['report_revision'] != 1 \
                    or request['action']['type'] != 'publish_owner_portal_report_v2' \
                    or request['action']['target'] != {'target_id': TARGET, 'media_type': 'application/json'} \
                    or request['report_payload_sha256'] != request['action']['content_sha256']:
                raise ValueError()
            for identifier in (request['proposal_id'], request['case_id']):
                IsolatedPortalPublicationStore._id(identifier)
            digest, size = request['action']['content_sha256'], request['action']['content_bytes']
            if not HEX.fullmatch(digest) or type(size) is not int or not 1 <= size <= 131072:
                raise ValueError()
            created, expires = (datetime.fromisoformat(request[name]) for name in ('created_at', 'expires_at'))
            if created.tzinfo is None or expires.tzinfo is None or expires-created != timedelta(seconds=86400):
                raise ValueError()
            return request
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, HTTPException):
            raise HTTPException(503, 'Invalid stored publication binding') from None

    @staticmethod
    def receipt(value, action):
        try:
            request = IsolatedPortalPublicationStore.request_binding(value)
            pub = value['publication']
            if value['action_id'] != action or value['decision'] != 'approved' or not isinstance(pub, dict) \
                    or pub['target_id'] != TARGET:
                raise ValueError()
            for identifier in (action, pub['publication_id'], request['proposal_id'], request['case_id']):
                IsolatedPortalPublicationStore._id(identifier)
            digest, size = request['action']['content_sha256'], request['action']['content_bytes']
            accepted = datetime.fromisoformat(pub['accepted_at'])
            if accepted.tzinfo is None or not datetime.fromisoformat(request['created_at']) <= accepted < datetime.fromisoformat(request['expires_at']):
                raise ValueError()
            return {'action_id': action, 'publication': {name: pub[name] for name in ('publication_id', 'accepted_at', 'target_id')},
                    'request_id': request['proposal_id'],
                    'request_sha256': value['request_sha256'], 'case_id': request['case_id'],
                    'revision': 1, 'content_sha256': digest, 'content_bytes': size,
                    'publication_semantics': request['publication_semantics']}
        except (KeyError, TypeError, ValueError, AttributeError, HTTPException):
            raise HTTPException(503, 'Invalid stored publication binding') from None

    def accept(self, action, key):
        action = self._id(action)
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', key):
            raise HTTPException(422, 'Bounded acceptance key required')
        value = self._query('SELECT retail.api_accept_portal_publication_v2(%s,%s)', (action, key), True,
                            lambda value: self.receipt(value, action))
        return self.receipt(value, action)  # Only after successful commit.

    def reconcile(self, action):
        action = self._id(action)
        value = self._query('SELECT retail.api_portal_publication_state_v2(%s)', (action,))
        return None if value is None or value.get('publication') is None else self.receipt(value, action)

    def request(self, session, request):
        value = self._query('SELECT retail.api_owner_portal_request_v3(%s,%s)',
                            (self._session(session), self._id(request)), locks=True)
        if value is None:
            raise HTTPException(404, 'Review object not found')
        if self.request_binding(value)['proposal_id'] != request:
            raise HTTPException(503, 'Invalid stored publication binding')
        return value

    def publication(self, session, action, export=False):
        action = self._id(action)
        sql = ('SELECT retail.api_owner_portal_export_v2(%s,%s)' if export else
               'SELECT retail.api_owner_portal_receipt_v2(%s,%s)')
        value = self._query(sql, (self._session(session), action), locks=True)
        if value is None:
            raise HTTPException(404, 'Publication object not found')
        try:
            receipt = self.receipt(value['receipt'], action)
            if not export:
                return receipt
            body = value['content_text'].encode('utf-8')
            if len(body) != receipt['content_bytes'] or sha256(body).hexdigest() != receipt['content_sha256']:
                raise ValueError()
        except (KeyError, TypeError, AttributeError, UnicodeError, ValueError):
            raise HTTPException(503, 'Invalid stored publication binding') from None
        return receipt, body


def install_isolated_publication_reads(app, store, key):
    """Explicit test-app installation only; no publication/approval POST route."""
    if not isinstance(store, IsolatedPortalPublicationStore):
        raise ValueError('Isolated store required')
    app.add_middleware(PortalGuard, store=store, key=key)
    _install_read_routes(app, store)


def _install_read_routes(app, store):
    """Shared fixed routes; middleware installation belongs to the installer."""

    @app.get('/portal/v2/requests/{request_id}')
    async def request_read(request_id: str, request: Request):
        value = await run_in_threadpool(store.request, request.state.portal_digest, request_id)
        return Response(json.dumps(value), media_type='application/json', headers=HEADERS)

    @app.get('/portal/v2/publications/{action_id}')
    async def receipt_read(action_id: str, request: Request):
        value = await run_in_threadpool(store.publication, request.state.portal_digest, action_id)
        return Response(json.dumps(value), media_type='application/json', headers=HEADERS)

    @app.get('/portal/v2/publications/{action_id}/export')
    async def export_read(action_id: str, request: Request):
        receipt, body = await run_in_threadpool(store.publication, request.state.portal_digest, action_id, True)
        return Response(body, media_type='application/json', headers={**HEADERS,
            'Content-Disposition': f'attachment; filename="report-{receipt["case_id"]}-revision-1.json"',
            'X-Report-SHA256': receipt['content_sha256'], 'X-Publication-ID': receipt['publication']['publication_id']})
