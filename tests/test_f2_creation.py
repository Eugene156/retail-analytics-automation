"""Offline synthetic contract tests; SQLite is not proof of PostgreSQL deployment."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import threading
import time
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from api.f2_creation import BASE, VERIFY, Creation, F2Middleware, Ledger, persisted_evidence, sign, verify
from api.portal import UAT_BOUNDARY, digest, session_csrf
from test_wp4_portal import call

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = '00000000-0000-0000-0000-000000000001'
CASE = '00000000-0000-0000-0000-000000000002'
REQUEST = '00000000-0000-0000-0000-000000000003'
SESSION = 'a' * 64
KEY = b'synthetic-creation-key-32-bytes-only'
NOW = 100000
RECEIPT = dict(status='AWAITING_APPROVAL', case_id=CASE, request_id=REQUEST, report_sha256='b'*64)


class Owner:
    def identity(self, session):
        if session != digest(SESSION):
            raise HTTPException(401, 'Unauthorized')
        return OPERATOR

    def review(self, session, case, request):
        self.identity(session)
        if (case, request) != (CASE, REQUEST):
            raise ValueError()
        return dict(request={'report_payload_sha256': 'b'*64, 'reviewer_id': OPERATOR,
                             'action':{'target':{'target_id':'local-owner-portal-report-v2'}}},
                    request_sha256='e'*64, report_text='Synthetic isolated report', review_receipt=None, decision=None,
                    publication=None, decision_enabled=True, review_status='pending_review')


class Database:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY, operator_id TEXT NOT NULL, nonce TEXT UNIQUE NOT NULL,
                state TEXT CHECK(state IN ('DISPATCHING','ADMITTED','UNCERTAIN','CREATED')) NOT NULL,
                execution_id TEXT UNIQUE, result TEXT,
                CHECK((state='CREATED')=(result IS NOT NULL)),
                CHECK(state NOT IN ('ADMITTED','CREATED') OR execution_id IS NOT NULL));
                CREATE UNIQUE INDEX unresolved ON operations(operator_id)
                  WHERE state IN ('DISPATCHING','ADMITTED','UNCERTAIN');''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        class Adapter:
            def execute(self, sql, args=()):
                return db.execute(sql.replace('f2_creation.operations', 'operations').replace('%s', '?'), args)
        try:
            with db:
                yield Adapter()
        finally:
            db.close()


class F2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=ROOT / '.local')
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / 'ledger.sqlite'))
        self.ledger = Ledger(self.db.connect)
        self.operation = str(uuid4())
        self.creation = Creation(Owner(), self.ledger, KEY, clock=lambda: NOW)
        self.sent = 0
        def transport(e):
            self.sent += 1
            self.creation.admit(e, '123')
            return deepcopy(RECEIPT)
        self.creation.transport = transport

    def envelope(self):
        return sign(KEY, self.operation, 'c'*64, NOW)

    def app(self):
        app = FastAPI()
        app.add_middleware(F2Middleware, creation=self.creation)
        return app

    def headers(self):
        return [(b'host', UAT_BOUNDARY.host.encode()), (b'origin', UAT_BOUNDARY.origin.encode()),
                (b'cookie', (UAT_BOUNDARY.session+'='+SESSION).encode()), (b'content-type', b'application/json')]

    def browser(self, headers=None, payload=None):
        body = json.dumps(payload or {'csrf': session_csrf(SESSION), 'operation_id': self.operation}).encode()
        return call(self.app(), BASE+'/create', 'POST', body, self.headers() if headers is None else headers)

    def test_signature_valid(self):
        verify(KEY, self.envelope(), NOW)

    def test_signature_binding_all_fields_and_shape(self):
        for name, value in dict(method='GET', path='/other', audience='other', timestamp=NOW-1,
                                nonce='d'*64, operation_id=str(uuid4()), body={'report_profile':'other'}, signature='0'*64).items():
            with self.subTest(name=name), self.assertRaises(HTTPException):
                e = self.envelope(); e[name] = value
                verify(KEY, e, NOW)
        for e in [dict(self.envelope(), unexpected=True), {k:v for k,v in self.envelope().items() if k!='nonce'}]:
            with self.assertRaises(HTTPException): verify(KEY, e, NOW)

    def test_expiry_future_and_wrong_key(self):
        for ts in (NOW-31, NOW+3):
            with self.assertRaises(HTTPException): verify(KEY, sign(KEY,self.operation,'c'*64,ts), NOW)
        with self.assertRaises(HTTPException): verify(b'x'*32, self.envelope(), NOW)

    def test_valid_creation_and_duplicate_operation_no_dispatch(self):
        value = self.creation.create(self.operation, OPERATOR, digest(SESSION))
        self.assertEqual(value['state'], 'CREATED')
        self.assertEqual(value['result']['status'], 'AWAITING_APPROVAL')
        self.assertEqual(value['result']['review_url'], f'/portal/cases/{CASE}/requests/{REQUEST}')
        self.assertEqual(self.creation.create(self.operation, OPERATOR, digest(SESSION)), value)
        self.assertEqual(self.sent, 1)

    def test_concurrent_replay_single_admission(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        def attempt(_):
            try: self.creation.admit(self.envelope(), '123'); return True
            except HTTPException: return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(attempt, range(8))), 1)

    def test_concurrent_duplicate_creation_single_transport(self):
        def attempt(_):
            return self.creation.create(self.operation, OPERATOR, digest(SESSION))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(attempt, range(6)))
        self.assertEqual(self.sent, 1)

    def test_nonce_unique_for_different_operations_and_owners(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        with self.assertRaises(HTTPException):
            self.ledger.reserve(str(uuid4()), str(uuid4()), 'c'*64)

    def test_unknown_valid_ticket_cannot_admit(self):
        with self.assertRaises(HTTPException): self.creation.admit(self.envelope(), '123')

    def test_invalid_admission_cannot_reach_core(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        e = self.envelope(); e['signature'] = '0'*64
        with self.assertRaises(HTTPException): self.creation.admit(e, '123')
        self.assertEqual(self.ledger.read(self.operation, OPERATOR)['state'], 'DISPATCHING')

    def test_new_process_objects_preserve_replay_and_operation_blocks(self):
        self.creation.create(self.operation, OPERATOR, digest(SESSION))
        restarted = Creation(Owner(), Ledger(self.db.connect), KEY, transport=lambda _: self.fail('redispatch'), clock=lambda: NOW)
        self.assertEqual(restarted.create(self.operation, OPERATOR, digest(SESSION))['state'], 'CREATED')
        with self.assertRaises(HTTPException): restarted.admit(self.envelope(), '124')

    def test_timeout_before_and_after_admission_blocks_retry_and_new_operation(self):
        for admitted in (False, True):
            with self.subTest(admitted=admitted):
                # Distinct operator for each isolated attempt.
                operation, operator = str(uuid4()), str(uuid4())
                def transport(e):
                    if admitted: self.creation.admit(e, '345')
                    raise TimeoutError('synthetic')
                self.creation.transport = transport
                value = self.creation.create(operation, operator, digest(SESSION))
                self.assertEqual(value['state'], 'UNCERTAIN')
                self.assertFalse(value['retry_allowed'])
                with self.assertRaises(HTTPException): self.creation.create(str(uuid4()), operator, digest(SESSION))
                self.assertEqual(self.creation.create(operation, operator, digest(SESSION))['state'], 'UNCERTAIN')

    def test_saved_signature_cannot_admit_after_timeout_or_restart(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        self.ledger.uncertain(self.operation)
        restarted = Creation(Owner(), Ledger(self.db.connect), KEY, clock=lambda: NOW)
        with self.assertRaises(HTTPException): restarted.admit(self.envelope(), '123')

    def test_read_only_evidence_reconciliation_never_dispatches(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        self.creation.admit(self.envelope(), '123')
        self.ledger.uncertain(self.operation)
        observation = dict(execution_id='123', workflow_id='p12-create-report-v1', success=True,
            operation_id=self.operation, core_workflow_id='p12-report-core-v2', result=RECEIPT)
        value = self.creation.reconcile(self.operation, OPERATOR, digest(SESSION), lambda _: observation)
        self.assertEqual(value['state'], 'CREATED')
        self.assertEqual(self.sent, 0)

    def test_wrong_or_missing_reconciliation_evidence_keeps_operation_closed(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        self.creation.admit(self.envelope(), '123')
        self.ledger.uncertain(self.operation)
        for observed in (None, {'execution_id':'124'}, {'execution_id':'123','success':False}):
            with self.assertRaises(HTTPException):
                self.creation.reconcile(self.operation, OPERATOR, digest(SESSION), lambda _: observed)
        self.assertEqual(self.ledger.read(self.operation, OPERATOR)['state'], 'UNCERTAIN')
        self.assertEqual(self.sent, 0)

    def test_crash_dispatching_and_admitted_never_rekey(self):
        self.ledger.reserve(self.operation, OPERATOR, 'c'*64)
        restarted = Creation(Owner(), Ledger(self.db.connect), KEY, transport=lambda _: self.fail('retry'), clock=lambda: NOW)
        self.assertEqual(restarted.create(self.operation, OPERATOR, digest(SESSION))['state'], 'DISPATCHING')
        self.creation.admit(self.envelope(), '123')
        self.assertEqual(restarted.create(self.operation, OPERATOR, digest(SESSION))['state'], 'ADMITTED')
        with self.assertRaises(HTTPException): restarted.create(str(uuid4()), OPERATOR, digest(SESSION))

    def test_invalid_workflow_receipt_is_uncertain(self):
        self.creation.transport = lambda _: {'status':'PUBLISHED'}
        self.assertEqual(self.creation.create(self.operation, OPERATOR, digest(SESSION))['state'], 'UNCERTAIN')

    def test_ambiguous_reservation_commit_never_dispatches(self):
        @contextmanager
        def ambiguous():
            with self.db.connect() as db:
                yield db
            raise TimeoutError('synthetic lost commit acknowledgement')
        self.creation.ledger = Ledger(ambiguous)
        with self.assertRaises(TimeoutError):
            self.creation.create(self.operation, OPERATOR, digest(SESSION))
        self.creation.ledger = self.ledger
        self.assertEqual(self.creation.create(self.operation, OPERATOR, digest(SESSION))['state'], 'DISPATCHING')
        self.assertEqual(self.sent,0)

    def test_final_states_are_read_from_existing_owner_review_without_writes(self):
        from unittest.mock import patch
        self.creation.create(self.operation,OPERATOR,digest(SESSION))
        original = self.creation.owner.review(digest(SESSION),CASE,REQUEST)
        for decision, publication, expected in [('approved',None,'APPROVED'),
                ('approved',{'receipt':'synthetic'},'PUBLISHED'),('rejected',None,'REJECTED')]:
            value = dict(original,decision=decision,publication=publication)
            with patch.object(self.creation.owner,'review',return_value=value):
                status, body, _=call(self.app(),BASE+'/operations/'+self.operation,headers=self.headers())
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body)['review']['status'],expected)
            self.assertEqual(self.sent,1)

    def test_persisted_evidence_projection_rejects_missing_or_retried_gate(self):
        snapshot=json.loads((ROOT/'workflows/f2_create_report_staged.json').read_text())
        def run(value): return [{'data':{'main':[[{'json':value}]]}}]
        runs={'Verify and atomically admit':run(dict(admitted=True,operation_id=self.operation,execution_id='123')),
              'Require committed admission':run({'operation_id':self.operation}),
              'Create verified report and approval request':run(RECEIPT)}
        execution=dict(id='123',status='success',finished=True,workflowData=snapshot,data={'resultData':{'runData':runs}})
        self.assertEqual(persisted_evidence(execution)['operation_id'],self.operation)
        runs['Verify and atomically admit'] *= 2
        with self.assertRaises(HTTPException): persisted_evidence(execution)

    def test_owner_review_binding_required(self):
        with self.assertRaises(ValueError):
            self.creation.validate_result(digest(SESSION), dict(RECEIPT, report_sha256='f'*64))

    def test_unauthorized_browser_denied_despite_correct_origin_and_csrf(self):
        headers = [(k,v) for k,v in self.headers() if k != b'cookie']
        self.assertEqual(self.browser(headers)[0], 401)
        headers = [(k, v.replace(SESSION.encode(), b'f'*64)) for k,v in self.headers()]
        self.assertEqual(self.browser(headers)[0], 401)
        self.assertEqual(self.sent, 0)

    def test_host_origin_csrf_and_duplicate_headers(self):
        for name, value, status in [(b'host',b'localhost:18082',400),(b'origin',b'http://evil.invalid',403)]:
            headers = [(k, value if k==name else v) for k,v in self.headers()]
            self.assertEqual(self.browser(headers)[0], status)
        self.assertEqual(self.browser([(k,v) for k,v in self.headers() if k!=b'origin'])[0], 403)
        self.assertEqual(self.browser(self.headers()+[(b'host', UAT_BOUNDARY.host.encode())])[0], 400)
        self.assertEqual(self.browser(payload={'csrf':'0'*64,'operation_id':self.operation})[0],403)
        self.assertEqual(self.sent,0)

    def test_duplicate_json_query_and_get_creation_denied(self):
        body = ('{"csrf":"'+session_csrf(SESSION)+'","operation_id":"'+self.operation+'","operation_id":"'+self.operation+'"}').encode()
        self.assertEqual(call(self.app(), BASE+'/create','POST',body,self.headers())[0],400)
        self.assertEqual(call(self.app(), BASE+'/create','GET',headers=self.headers())[0],404)
        self.assertEqual(call(self.app(), BASE+'/create','POST',b'{}',self.headers(),query=b'x=1')[0],400)

    def test_exact_tracking_get_redirects_without_authorizing_creation(self):
        for headers in (self.headers(), [(b'host', UAT_BOUNDARY.host.encode())]):
            code, body, returned = call(self.app(), BASE, headers=headers, query=b'utm_source=chatgpt.com')
            self.assertEqual(code, 303)
            self.assertEqual(dict(returned)[b'location'], BASE.encode())
            self.assertEqual(body, b'')
            self.assertEqual(dict(returned)[b'cache-control'], b'no-store')
        self.assertEqual(call(self.app(), BASE, headers=self.headers())[0], 200)
        self.assertEqual(call(self.app(), BASE, headers=[(b'host', UAT_BOUNDARY.host.encode())])[0], 303)
        self.assertEqual(self.sent, 0)

    def test_tracking_redirect_rejects_variants_and_preserves_boundaries(self):
        queries = (b'utm_source=chatgpt.com&utm_source=chatgpt.com',
            b'utm_source=other&utm_source=chatgpt.com', b'utm_source=chatgpt.com&extra=1',
            b'extra=1&utm_source=chatgpt.com', b'utm_source=other', b'anything=1',
            b'utm_source=chatgpt.com&', b'utm_source=chatgpt%2Ecom', b'%75tm_source=chatgpt.com')
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(call(self.app(), BASE, headers=self.headers(), query=query)[0], 400)
        for path, method in ((BASE, 'POST'), (BASE, 'HEAD'), (BASE+'/create', 'POST'),
                             (BASE+'/assets/f2.css', 'GET'), (VERIFY, 'POST')):
            with self.subTest(path=path, method=method):
                self.assertEqual(call(self.app(), path, method, headers=self.headers(),
                                      query=b'utm_source=chatgpt.com')[0], 400)
        for extra, expected in (([(b'host',b'localhost:18082')],400),
                                ([(b'origin',b'http://evil.invalid')],403),
                                ([(b'authorization',b'Bearer synthetic')],400),
                                ([(b'sec-fetch-site',b'cross-site')],403)):
            names = {k for k, _ in extra}
            headers = [(k,v) for k,v in self.headers() if k not in names] + extra
            self.assertEqual(call(self.app(), BASE, headers=headers, query=b'utm_source=chatgpt.com')[0], expected)
        self.assertEqual(self.sent, 0)

    def test_page_assets_no_secret_or_internal_url_and_status_owner_scope(self):
        for path in (BASE, BASE+'/assets/overview.css', BASE+'/assets/f2.css', BASE+'/assets/f2.js'):
            status, body, headers = call(self.app(), path, headers=self.headers())
            self.assertEqual(status,200)
            for secret in (KEY, SESSION.encode(), b'http://n8n', b'/webhook/'):
                self.assertNotIn(secret,body)
            self.assertIn(b'no-store',dict(headers)[b'cache-control'])
        self.creation.create(self.operation, OPERATOR, digest(SESSION))
        with self.assertRaises(HTTPException): self.ledger.read(self.operation,str(uuid4()))

    def test_f2_stylesheet_contract_and_authentication(self):
        path = BASE + '/assets/f2.css'
        status, body, headers = call(self.app(), path, headers=self.headers())
        self.assertEqual(status, 200)
        self.assertTrue(dict(headers)[b'content-type'].startswith(b'text/css'))
        self.assertEqual(dict(headers)[b'x-content-type-options'], b'nosniff')
        self.assertEqual(body, (ROOT/'api/f2_assets/f2.css').read_bytes())
        for selector in (b'.f2-panel', b'.f2-steps', b'.f2-panel button', b'@media'):
            self.assertIn(selector, body)
        status, page, _ = call(self.app(), BASE, headers=self.headers())
        self.assertEqual(status, 200)
        self.assertIn(b'href="/portal/f2/assets/f2.css"', page)
        self.assertEqual(call(self.app(), path, headers=[(b'host', UAT_BOUNDARY.host.encode())])[0], 303)
        self.assertEqual(self.sent, 0)

    def test_parallel_assets_preserve_serial_owner_authentication(self):
        # The real owner SQL adapter has one nonblocking database slot.
        owner = self.creation.owner
        slot = threading.BoundedSemaphore(1)
        rejected = []
        def identity(session):
            if not slot.acquire(blocking=False):
                rejected.append(True)
                raise HTTPException(429, 'Portal is busy')
            try:
                time.sleep(.02)
                return owner.identity(session)
            finally:
                slot.release()
        class SerialOwner:
            pass
        serial = SerialOwner()
        serial.identity = identity
        self.creation.owner = serial
        app = self.app()
        async def asset(name):
            messages = []
            async def receive():
                return {'type':'http.request', 'body':b'', 'more_body':False}
            async def send(message):
                messages.append(message)
            path = BASE+'/assets/'+name
            scope = {'type':'http', 'asgi':{'version':'3.0'}, 'http_version':'1.1',
                     'scheme':'http', 'method':'GET', 'path':path, 'raw_path':path.encode(),
                     'query_string':b'', 'headers':self.headers(), 'root_path':''}
            await app(scope, receive, send)
            return next(m['status'] for m in messages if m['type']=='http.response.start')
        async def parallel():
            return await asyncio.gather(*(asset(name) for name in ('overview.css','f2.css','f2.js')))
        self.assertEqual(asyncio.run(parallel()), [200, 200, 200])
        self.assertEqual(rejected, [])
        self.assertEqual(self.sent, 0)

    def test_verifier_rejects_browser_and_has_no_core_executor(self):
        self.assertEqual(call(self.app(),VERIFY,'POST',b'{}',self.headers())[0],400)
        with self.assertRaises(HTTPException): self.creation.admit(self.envelope(),'not-an-id')

    def test_workflow_manual_unchanged_webhook_gated_and_no_credentials(self):
        original = json.loads((ROOT/'workflows/p12_create_report.json').read_text())
        staged = json.loads((ROOT/'workflows/f2_create_report_staged.json').read_text())
        self.assertEqual(staged['id'],original['id'])
        self.assertFalse(staged['active'])
        self.assertEqual(staged['nodes'][:2],original['nodes'])
        self.assertEqual(staged['connections']['Manual Trigger'],original['connections']['Manual Trigger'])
        chain=['F2 signed creation','Check F2 envelope','Verify and atomically admit','Require committed admission','Create verified report and approval request']
        for a,b in zip(chain,chain[1:]):
            self.assertEqual(staged['connections'][a]['main'],[[{'node':b,'type':'main','index':0}]])
        for node in staged['nodes'][2:]:
            self.assertNotIn('credentials',node)
            self.assertFalse(node.get('retryOnFail',False))
            self.assertFalse(node.get('continueOnFail',False))
        code = next(n['parameters']['jsCode'] for n in staged['nodes'] if n['name']=='Require committed admission')
        self.assertIn('a.admitted!==true',code)
        envelope_code = next(n['parameters']['jsCode'] for n in staged['nodes'] if n['name']=='Check F2 envelope')
        self.assertIn("$execution.mode !== 'production'",envelope_code)
        self.assertNotIn(KEY.decode(),json.dumps(staged))

    def test_postgres_artifact_scope_and_atomic_constraints(self):
        sql=(ROOT/'db/demo/f2_creation.sql').read_text()
        for required in ('raa.f2_database','PRIMARY KEY','nonce text NOT NULL UNIQUE','CREATE UNIQUE INDEX',
                         'UNCERTAIN','NOLOGIN NOSUPERUSER','has_function_privilege'):
            self.assertIn(required,sql)
        self.assertNotIn('GRANT EXECUTE',sql)
        self.assertNotIn('DROP ',sql)


if __name__ == '__main__':
    unittest.main()
