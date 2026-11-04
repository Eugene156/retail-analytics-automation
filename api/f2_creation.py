"""Opt-in F2 admission. No installation, SQL migration or dispatch at import time."""
from contextlib import contextmanager
import asyncio
from hashlib import sha256
from html import escape
import hmac
import json
from pathlib import Path
import re
import secrets
import time
from urllib.request import Request as URLRequest, build_opener, ProxyHandler
from uuid import UUID

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse, Response

from api.portal import UAT_BOUNDARY, cookies, digest, session_csrf
from api.p12_demo import NoRedirect

PATH = '/webhook/f2-create-report-v1'
HOOK = 'http://n8n:5678' + PATH
VERIFY = '/f2-internal/admit'
BASE = '/portal/f2'
BODY = {'report_profile': 'p1-demo-v1'}
ASSETS = Path(__file__).with_name('f2_assets')
HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
           'Referrer-Policy': 'same-origin', 'X-Frame-Options': 'DENY',
           'Content-Security-Policy': "default-src 'none'; style-src 'self'; script-src 'self'; "
           "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"}


def identity(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Canonical UUID required')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def message(e):
    return canonical([e['method'], e['path'], e['audience'], e['timestamp'],
                      e['nonce'], e['operation_id'], sha256(canonical(e['body']).encode()).hexdigest()]).encode()


def sign(key, operation, nonce, timestamp):
    e = dict(method='POST', path=PATH, audience='raa-f2-report-creation-v1',
             timestamp=timestamp, nonce=nonce, operation_id=operation, body=BODY.copy())
    e['signature'] = hmac.new(key, message(e), sha256).hexdigest()
    return e


def verify(key, e, now):
    try:
        if not isinstance(e, dict) or set(e) != {'method', 'path', 'audience', 'timestamp',
                                                'nonce', 'operation_id', 'body', 'signature'}:
            raise ValueError()
        identity(e['operation_id'])
        if (e['method'] != 'POST' or e['path'] != PATH or e['audience'] != 'raa-f2-report-creation-v1'
                or type(e['timestamp']) is not int or not now - 30 <= e['timestamp'] <= now + 2
                or not isinstance(e['nonce'], str) or not re.fullmatch('[a-f0-9]{64}', e['nonce'])
                or e['body'] != BODY or not isinstance(e['signature'], str)
                or not re.fullmatch('[a-f0-9]{64}', e['signature'])
                or not hmac.compare_digest(e['signature'], hmac.new(key, message(e), sha256).hexdigest())):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(403, 'Invalid or expired creation authorization') from None


class Ledger:
    """All writes commit before returning. No dispatch after an ambiguous commit."""
    def __init__(self, factory):
        self.factory = factory

    def reserve(self, operation, operator, nonce):
        with self.factory() as db:
            row = db.execute('INSERT INTO f2_creation.operations '
                '(operation_id,operator_id,nonce,state) VALUES (%s,%s,%s,\'DISPATCHING\') '
                'ON CONFLICT DO NOTHING RETURNING operation_id', (operation, operator, nonce)).fetchone()
            if row:
                return True
            known = db.execute('SELECT operation_id FROM f2_creation.operations '
                               'WHERE operation_id=%s AND operator_id=%s', (operation, operator)).fetchone()
            if not known:
                raise HTTPException(409, 'An unresolved operation exists; reconcile it before creating another report')
            return False

    def admit(self, e, execution):
        with self.factory() as db:
            row = db.execute("UPDATE f2_creation.operations SET state='ADMITTED', execution_id=%s "
                "WHERE operation_id=%s AND nonce=%s AND state='DISPATCHING' RETURNING operation_id",
                (execution, e['operation_id'], e['nonce'])).fetchone()
            if not row:
                raise HTTPException(409, 'Unknown, replayed or uncertain creation authorization')

    def uncertain(self, operation):
        with self.factory() as db:
            db.execute("UPDATE f2_creation.operations SET state='UNCERTAIN' "
                       "WHERE operation_id=%s AND state IN ('DISPATCHING','ADMITTED')", (operation,))

    def complete(self, operation, result):
        with self.factory() as db:
            row = db.execute("UPDATE f2_creation.operations SET state='CREATED', result=%s "
                "WHERE operation_id=%s AND state='ADMITTED' RETURNING operation_id",
                (canonical(result), operation)).fetchone()
            if not row:
                raise HTTPException(409, 'Creation receipt requires reconciliation')

    def reconcile(self, operation, operator, execution, result):
        with self.factory() as db:
            row = db.execute("UPDATE f2_creation.operations SET state='CREATED', result=%s "
                "WHERE operation_id=%s AND operator_id=%s AND execution_id=%s "
                "AND state IN ('ADMITTED','UNCERTAIN') RETURNING operation_id",
                (canonical(result), operation, operator, execution)).fetchone()
            if not row:
                raise HTTPException(409, 'Reconciliation binding changed; preserve the operation')

    def read(self, operation, operator):
        with self.factory() as db:
            row = db.execute('SELECT state,execution_id,result FROM f2_creation.operations '
                             'WHERE operation_id=%s AND operator_id=%s', (operation, operator)).fetchone()
        if not row:
            raise HTTPException(404, 'Operation not found')
        # DISPATCHING/ADMITTED can survive a crash: never imply a safe retry.
        return dict(operation_id=operation, state=row[0], execution_id=row[1],
                    result=json.loads(row[2]) if row[2] else None,
                    retry_allowed=False)


def dispatch(envelope):
    request = URLRequest(HOOK, data=canonical(envelope).encode(), method='POST',
                         headers={'Content-Type': 'application/json'})
    # Fixed destination, no proxy environment, redirect following or transport retries.
    with build_opener(ProxyHandler({}), NoRedirect).open(request, timeout=245) as response:
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            raise ValueError('Uncertain workflow response')
        return json.loads(raw)


def persisted_evidence(execution):
    """Project a trusted n8n execution read, never export its raw headers/data.

    A deployment operator supplies the authenticated read-only reader. Fail
    closed on retries, missing snapshots, alternate graphs or partial outputs.
    """
    try:
        if execution['status'] != 'success' or execution['finished'] is not True:
            raise ValueError()
        snapshot = execution['workflowData']
        if snapshot['id'] != 'p12-create-report-v1':
            raise ValueError()
        nodes = {n['name']: n for n in snapshot['nodes']}
        core = nodes['Create verified report and approval request']
        if (core['type'] != 'n8n-nodes-base.executeWorkflow'
                or core['parameters']['workflowId']['value'] != 'p12-report-core-v2'):
            raise ValueError()
        runs = execution['data']['resultData']['runData']
        def output(name):
            attempts = runs[name]
            if len(attempts) != 1 or attempts[0].get('error'):
                raise ValueError()
            items = attempts[0]['data']['main']
            if len(items) != 1 or len(items[0]) != 1:
                raise ValueError()
            return items[0][0]['json']
        gate = output('Verify and atomically admit')
        operation = output('Require committed admission')['operation_id']
        if (gate['admitted'] is not True or gate['operation_id'] != operation
                or gate['execution_id'] != str(execution['id'])):
            raise ValueError()
        return dict(execution_id=str(execution['id']), workflow_id=snapshot['id'],
                    success=True, operation_id=operation, core_workflow_id='p12-report-core-v2',
                    result=output('Create verified report and approval request'))
    except (KeyError, TypeError, IndexError, ValueError):
        raise HTTPException(409, 'Persisted workflow evidence is incomplete; preserve the operation') from None


class Creation:
    def __init__(self, owner, ledger, key, transport=dispatch, clock=time.time):
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError('Separate 256-bit signing key required')
        self.owner, self.ledger, self.key = owner, ledger, key
        self.transport, self.clock = transport, clock

    def create(self, operation, operator, session):
        nonce = secrets.token_hex(32)
        if not self.ledger.reserve(operation, operator, nonce):
            return self.ledger.read(operation, operator)
        try:
            result = self.transport(sign(self.key, operation, nonce, int(self.clock())))
            result = self.validate_result(session, result)
            self.ledger.complete(operation, result)
        except Exception:
            # Even a 4xx response is not a license to submit another operation.
            try:
                self.ledger.uncertain(operation)
            except Exception:
                pass  # Persisted DISPATCHING/ADMITTED also blocks new operations.
        return self.ledger.read(operation, operator)

    def validate_result(self, session, result, pending=True):
        if not isinstance(result, dict) or result.get('status') != 'AWAITING_APPROVAL':
            raise ValueError('No verified creation receipt')
        case, request = identity(result['case_id']), identity(result['request_id'])
        value = self.owner.review(session, case, request)
        binding = value['request']
        if (binding['report_payload_sha256'] != result['report_sha256']
                or binding['reviewer_id'] != str(self.owner.identity(session))
                or pending and (value['decision'] is not None or value['publication'] is not None
                                or not value['decision_enabled'])):
            raise ValueError('Unexpected review binding')
        return dict(status='AWAITING_APPROVAL', case_id=case, request_id=request,
                    report_sha256=result['report_sha256'],
                    review_url=f'/portal/cases/{case}/requests/{request}')

    def reconcile(self, operation, operator, session, evidence_reader):
        """Operator-only recovery helper, deliberately not an HTTP endpoint.

        evidence_reader is trusted code reading persisted n8n parent execution
        data, never a browser payload. It must return the actual execution ID,
        successful core-call output and its current parent workflow identity.
        Missing/failed/ambiguous evidence leaves the admission closed forever.
        """
        if str(self.owner.identity(session)) != operator:
            raise HTTPException(401, 'Unauthorized')
        current = self.ledger.read(operation, operator)
        if current['state'] == 'CREATED':
            return current
        if not current['execution_id']:
            raise HTTPException(409, 'No admitted execution evidence; preserve the unresolved operation')
        observed = evidence_reader(current['execution_id'])
        if (not isinstance(observed, dict) or observed.get('execution_id') != current['execution_id']
                or observed.get('workflow_id') != 'p12-create-report-v1' or observed.get('success') is not True
                or observed.get('operation_id') != operation
                or observed.get('core_workflow_id') != 'p12-report-core-v2'):
            raise HTTPException(409, 'No unambiguous persisted creation evidence')
        result = self.validate_result(session, observed['result'], pending=False)
        self.ledger.reconcile(operation, operator, current['execution_id'], result)
        return self.ledger.read(operation, operator)

    def admit(self, e, execution):
        verify(self.key, e, int(self.clock()))
        if not isinstance(execution, str) or not re.fullmatch('[1-9][0-9]{0,18}', execution):
            raise HTTPException(422, 'Workflow execution binding required')
        self.ledger.admit(e, execution)
        return dict(admitted=True, operation_id=e['operation_id'], execution_id=execution)


class F2Middleware:
    """Reuse the owner session; do not extend or replace the decision middleware."""
    def __init__(self, app, creation):
        self.app, self.creation = app, creation
        # Browsers fetch CSS/JS concurrently; the unchanged owner SQL adapter
        # deliberately has one nonblocking slot. Queue these session checks
        # instead of losing authenticated assets to a local 429 race.
        self.identity_lock = asyncio.Lock()

    async def owner_identity(self, session_digest):
        try:
            await asyncio.wait_for(self.identity_lock.acquire(), timeout=5)
        except asyncio.TimeoutError:
            raise HTTPException(429, 'Portal is busy') from None
        try:
            return await run_in_threadpool(self.creation.owner.identity, session_digest)
        finally:
            self.identity_lock.release()

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not (path == VERIFY or path == BASE or path.startswith(BASE + '/')):
            return await self.app(scope, receive, send)
        try:
            response = await self.handle(scope, receive)
        except HTTPException as error:
            response = JSONResponse({'detail': error.detail}, error.status_code, headers=HEADERS)
        except (ValueError, UnicodeError, KeyError, TypeError):
            response = JSONResponse({'detail': 'Invalid creation request'}, 400, headers=HEADERS)
        except Exception:
            response = JSONResponse({'detail': 'Creation state unavailable; do not resubmit'}, 503, headers=HEADERS)
        await response(scope, receive, send)

    async def handle(self, scope, receive):
        path, method = scope['path'], scope['method']
        def values(name):
            return [v for k, v in scope['headers'] if k.lower() == name]
        internal = path == VERIFY
        hosts = [b'approval:8000'] if internal else [UAT_BOUNDARY.host.encode()]
        query = scope.get('query_string', b'')
        tracking_entry = method == 'GET' and path == BASE and query == b'utm_source=chatgpt.com'
        if values(b'host') != hosts or (query and not tracking_entry) or values(b'authorization'):
            raise HTTPException(400, 'Invalid creation boundary')
        if internal:
            if values(b'origin') or values(b'cookie'):
                raise HTTPException(400, 'Service request required')
        elif (values(b'origin') not in ([], [UAT_BOUNDARY.origin.encode()])
                or method == 'POST' and values(b'origin') != [UAT_BOUNDARY.origin.encode()]
                or (values(b'sec-fetch-site') not in ([], [b'none'], [b'same-origin'])
                    and not (path == BASE and method == 'GET' and not values(b'origin')
                             and values(b'sec-fetch-site') == [b'same-site']
                             and values(b'sec-fetch-mode') == [b'navigate']
                             and values(b'sec-fetch-dest') == [b'document']))):
            raise HTTPException(403, 'Invalid creation origin')
        if method not in ('GET', 'POST') or internal and method != 'POST':
            raise HTTPException(405, 'Method not allowed')
        if tracking_entry:
            # Fixed GET navigation only; the clean destination still requires owner auth.
            return RedirectResponse(BASE, 303, headers=HEADERS)
        raw, operator = None, None
        if not internal:
            raw = cookies(scope['headers'], UAT_BOUNDARY.session).get(UAT_BOUNDARY.session)
            if not raw:
                if method == 'GET':
                    return RedirectResponse('/portal/login', 303, headers=HEADERS)
                raise HTTPException(401, 'Owner sign-in required')
            operator = str(await self.owner_identity(digest(raw)))
            identity(operator)
        if method == 'POST':
            if values(b'content-type') != [b'application/json']:
                raise HTTPException(415, 'JSON required')
            request = Request(scope, receive)
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 4096:
                    raise HTTPException(413, 'Creation request too large')
            def unique(pairs):
                value = dict(pairs)
                if len(value) != len(pairs):
                    raise ValueError('Duplicate JSON fields')
                return value
            payload = json.loads(data, object_pairs_hook=unique)
            if not isinstance(payload, dict):
                raise ValueError()
            if internal:
                if set(payload) != {'envelope', 'execution_id'}:
                    raise ValueError()
                result = await run_in_threadpool(self.creation.admit, payload['envelope'], payload['execution_id'])
            else:
                if path != BASE + '/create' or set(payload) != {'csrf', 'operation_id'}:
                    raise ValueError()
                if not isinstance(payload['csrf'], str) or not hmac.compare_digest(payload['csrf'], session_csrf(raw)):
                    raise HTTPException(403, 'Invalid creation challenge')
                operation = identity(payload['operation_id'])
                result = await run_in_threadpool(self.creation.create, operation, operator, digest(raw))
            return JSONResponse(result, headers=HEADERS)
        if path == BASE:
            html = (ASSETS / 'index.html').read_text(encoding='utf-8').replace('__CSRF__', escape(session_csrf(raw)))
            return Response(html, media_type='text/html', headers=HEADERS)
        files = {'overview.css': (Path(__file__).with_name('overview_assets') / 'overview.css', 'text/css'),
                 'f2.css': (ASSETS / 'f2.css', 'text/css'), 'f2.js': (ASSETS / 'f2.js', 'text/javascript')}
        if path.startswith(BASE + '/assets/') and path.removeprefix(BASE + '/assets/') in files:
            file, media = files[path.removeprefix(BASE + '/assets/')]
            return Response(file.read_bytes(), media_type=media, headers=HEADERS)
        if path.startswith(BASE + '/operations/'):
            operation = identity(path.removeprefix(BASE + '/operations/'))
            result = await run_in_threadpool(self.creation.ledger.read, operation, operator)
            # Current owner review is authoritative; reading never decides or publishes.
            if result['result']:
                known = result['result']
                value = await run_in_threadpool(self.creation.owner.review, digest(raw), known['case_id'], known['request_id'])
                result['review_status'] = value['review_status']
                result['review'] = dict(
                    status=('PUBLISHED' if value['publication'] is not None else
                            'REJECTED' if value['decision'] == 'rejected' else
                            'APPROVED' if value['decision'] == 'approved' else 'AWAITING_APPROVAL'),
                    report_sha256=value['request']['report_payload_sha256'],
                    request_sha256=value['request_sha256'],
                    target=value['request']['action']['target']['target_id'],
                    report_text=value['report_text'], publication=value['publication'],
                    decision_receipt=value['review_receipt'])
            return JSONResponse(result, headers=HEADERS)
        raise HTTPException(404, 'Not found')


def configured_creation(owner, config):
    """Explicit opt-in only, with a distinct demo-only DB role and key file."""
    import psycopg
    f2 = config['f2_creation']
    db = f2['database']
    if (set(db) != {'host', 'dbname', 'user', 'password'} or db['host'] != 'postgres'
            or db['dbname'] != config['database'] or not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}', db['dbname'])
            or db['user'] != 'raa_f2_creation' or db['user'] in {v['user'] for v in config['stores'].values()}):
        raise ValueError('Separate restricted demo ledger role required')
    key_path = Path('/run/p12/f2-signing-key')
    key = bytes.fromhex(key_path.read_text(encoding='ascii').strip())
    if key.hex() in {config['portal_key'], config['service_token'], config['primary_token']}:
        raise ValueError('Distinct creation signing key required')
    @contextmanager
    def factory():
        with psycopg.connect(**db, connect_timeout=5) as connection:
            if connection.execute('SELECT current_database(),current_user').fetchone() != (db['dbname'], db['user']):
                raise ValueError('Unexpected ledger database')
            connection.execute("SET LOCAL statement_timeout='5s'")
            connection.execute("SET LOCAL lock_timeout='1s'")
            yield connection
    return Creation(owner, Ledger(factory), key)
