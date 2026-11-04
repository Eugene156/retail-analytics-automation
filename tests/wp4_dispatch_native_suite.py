"""Opt-in owner-run NTFS/real-DB suite, or clearly separate IPC-only checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from uuid import uuid4

from api.local_publication import WindowsPublicationFiles
from api.publication_dispatch import (DispatchBindingError, DispatchUncertain,
    IsolatedPublicationDispatcher, IsolatedPublicationStore, canonical_uuid)
from wp4_dispatch_ipc import PrivatePipe, PipeConnection

ROOT=Path(__file__).resolve().parents[1]
CONFIG=None


class MemoryFiles:
    def __init__(self): self.content=None; self.installs=0
    def reconcile(self,case,content,digest): return 'missing' if self.content is None else 'matching'
    def publish(self,case,content,digest,authorize,checkpoint=None):
        if not authorize(): raise RuntimeError('Test authorization denied')
        if self.content is not None: return 'reconciled'
        if checkpoint: checkpoint('staged')
        if not authorize(): raise RuntimeError('Test authorization denied')
        self.content=content; self.installs+=1
        if checkpoint: checkpoint('installed')
        return 'created'


def dispatcher(config,files):
    return IsolatedPublicationDispatcher(IsolatedPublicationStore(lambda:PipeConnection(config),config['database']),files)


def state(config,action):
    store=IsolatedPublicationStore(lambda:PipeConnection(config),config['database'])
    with store.transaction() as tx: return tx.state(action['action_id'])


def child(config,action,key,root=None,crash='receipt_pending'):
    # Credentials go through stdin only, never argv, exception or result output.
    value={'database':config['database'],'worker':config['worker'],'action':action['action_id'],
        'key':key,'root':str(root) if root else None,'crash':crash}
    code="import sys,runpy; sys.path.insert(0,'scripts'); runpy.run_path('tests/wp4_dispatch_native_suite.py',run_name='__main__')"
    process=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
    try:
        output,_=process.communicate(json.dumps(value),timeout=65)
        if len(output)>4096: raise RuntimeError('Bounded child result required')
        return process.returncode
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate(timeout=5)
        raise RuntimeError('Synthetic child timed out') from None


class Harness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller=PrivatePipe(CONFIG,'controller')
    @classmethod
    def tearDownClass(cls): cls.controller.close()
    def fixture(self,short=False): return self.controller.call('short_fixture' if short else 'fixture')
    def prepare(self,action,files):
        adapter=dispatcher(CONFIG,files)
        result=adapter.step(action['action_id'],'reconcile','initial-'+uuid4().hex)
        self.assertEqual(result['state'],'retryable')
        return adapter,'write-'+uuid4().hex


class BridgeTests(Harness):
    def test_bridge_fixture_target_uses_actual_outbox_path_not_missing_case_id(self):
        action=self.fixture()
        self.assertNotIn('case_id',action)
        root=ROOT/'.local'/'path-contract-only-not-created'
        snapshot=state(CONFIG,action)
        native=NativeTests('test_native_exact_bytes_ten_replays_no_rewrite')
        self.assertEqual(native.target(root,action),
            root/'reports'/'approved'/'v1'/snapshot['case_id']/'revision-1.json')
    def test_bridge_exact_bytes_and_ten_receipt_replays(self):
        action=self.fixture(); files=MemoryFiles(); adapter,key=self.prepare(action,files)
        self.assertEqual(adapter.step(action['action_id'],'write',key)['state'],'succeeded')
        self.assertEqual(files.content,CONFIG['base']['report'].encode())
        for _ in range(10): self.assertEqual(adapter.step(action['action_id'],'write',key)['state'],'succeeded')
        self.assertEqual(files.installs,1)
    def test_bridge_eof_rolls_back_uncommitted_claim(self):
        action=self.fixture(); conn=PipeConnection(CONFIG)
        try:
            conn.read_only=False
            conn.execute('SELECT retail.api_claim_publication_v1(%s,%s,%s)',
                (action['action_id'],'reconcile','uncommitted-'+uuid4().hex))
        finally: conn.close()
        self.assertEqual((state(CONFIG,action)['state'],state(CONFIG,action)['sequence']),('pending',0))
    def test_bridge_arbitrary_sql_refused_locally(self):
        conn=PipeConnection(CONFIG)
        try:
            with self.assertRaises(ValueError): conn.execute('SELECT * FROM retail.owner_credentials')
        finally: conn.close()
    def test_bridge_actual_worker_exit_rolls_back_receipt(self):
        action=self.fixture(); files=MemoryFiles(); adapter,key=self.prepare(action,files)
        self.assertEqual(child(CONFIG,action,key),77)
        self.assertEqual((state(CONFIG,action)['state'],state(CONFIG,action)['sequence']),('in_progress',3))
        time.sleep(30.1)
        recovered=adapter.step(action['action_id'],'reconcile','recovery-'+uuid4().hex)
        self.assertEqual((recovered['state'],recovered['write_attempts']),('retryable',1))


class NativeTests(Harness):
    def files(self):
        base=ROOT/'.local'/'wp4-publication-tests'; base.mkdir(parents=True,exist_ok=True)
        root=Path(tempfile.mkdtemp(prefix='dispatch-',dir=base))
        return root,WindowsPublicationFiles(root)
    def target(self,root,action):
        # Decision receipt outbox has relative_path, not case_id (migration 019).
        # This is a pure assertion helper; never create/read a supplied path here.
        relative=action.get('relative_path')
        if action.get('target_id')!='local-approved-report-json-v1' or not isinstance(relative,str):
            raise DispatchBindingError('Fixed synthetic fixture target required')
        parts=relative.split('/')
        if len(parts)!=5 or parts[:3]!=['reports','approved','v1'] or parts[4]!='revision-1.json':
            raise DispatchBindingError('Exact fixed fixture path required')
        canonical_uuid(parts[3])
        return root.joinpath(*parts)
    def wait_expiry(self,action):
        deadline=datetime.fromisoformat(state(CONFIG,action)['authorization_expires_at'])
        remaining=(deadline-datetime.now(timezone.utc)).total_seconds()+.3
        if remaining>25: raise RuntimeError('Bounded synthetic expiry required')
        if remaining>0: time.sleep(remaining)
    def test_native_exact_bytes_ten_replays_no_rewrite(self):
        action=self.fixture(); root,files=self.files(); adapter,key=self.prepare(action,files)
        self.assertEqual(adapter.step(action['action_id'],'write',key)['state'],'succeeded')
        target=self.target(root,action); before=target.stat().st_mtime_ns
        self.assertEqual(target.read_bytes(),CONFIG['base']['report'].encode())
        for _ in range(10): self.assertEqual(adapter.step(action['action_id'],'write',key)['state'],'succeeded')
        self.assertEqual(target.stat().st_mtime_ns,before)
    def test_native_two_concurrent_same_key_workers_single_artifact(self):
        action=self.fixture(); root,files=self.files(); adapter,key=self.prepare(action,files)
        barrier=threading.Barrier(2)
        def work():
            barrier.wait(timeout=10)
            for attempt in range(3):
                try: return dispatcher(CONFIG,WindowsPublicationFiles(root)).step(action['action_id'],'write',key)['state']
                except DispatchUncertain:
                    if attempt==2: raise
                    time.sleep(.3*(attempt+1))
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:work(),range(2)))
        self.assertEqual(outcomes,['succeeded','succeeded'])
        self.assertEqual(self.target(root,action).read_bytes(),CONFIG['base']['report'].encode())
        self.assertEqual(state(CONFIG,action)['write_attempts'],1)
    def test_native_actual_process_exits_and_expired_lease_reconciliation(self):
        pending=[]
        for point in ('claim_committed','staged','installed','receipt_pending','receipt_committed'):
            action=self.fixture(); root,files=self.files(); adapter,key=self.prepare(action,files)
            self.assertEqual(child(CONFIG,action,key,root,point),77)
            target=self.target(root,action)
            exists=point in ('installed','receipt_pending','receipt_committed')
            self.assertEqual(target.exists(),exists)
            before=target.stat().st_mtime_ns if exists else None
            if point=='staged': self.assertEqual(len(list(target.parent.glob('.staged-*'))),1)
            pending.append((point,action,root,files,adapter,key,before))
        time.sleep(30.1)
        for point,action,root,files,adapter,key,before in pending:
            replay=adapter.step(action['action_id'],'write',key)
            target=self.target(root,action)
            if point=='receipt_committed': self.assertEqual(replay['state'],'succeeded')
            else:
                self.assertIsNone(replay['observation'])
                recovered=adapter.step(action['action_id'],'reconcile','recover-'+uuid4().hex)
                if before is None:
                    self.assertEqual(recovered['state'],'retryable')
                    self.assertEqual(adapter.step(action['action_id'],'write','new-write-'+uuid4().hex)['state'],'succeeded')
                else: self.assertEqual(recovered['state'],'succeeded')
            self.assertEqual(target.read_bytes(),CONFIG['base']['report'].encode())
            if before is not None: self.assertEqual(target.stat().st_mtime_ns,before)
    def test_native_receipt_fault_retains_file_then_reconciles(self):
        action=self.fixture(); root,files=self.files(); adapter,key=self.prepare(action,files)
        self.controller.call('fault_on')
        try:
            with self.assertRaises(DispatchUncertain): adapter.step(action['action_id'],'write',key)
            target=self.target(root,action); before=target.stat().st_mtime_ns
            self.assertEqual(target.read_bytes(),CONFIG['base']['report'].encode())
            self.assertEqual(state(CONFIG,action)['sequence'],3)
        finally: self.controller.call('fault_off')
        self.assertEqual(adapter.step(action['action_id'],'write',key)['state'],'succeeded')
        self.assertEqual(target.stat().st_mtime_ns,before)
    def test_native_expiry_during_stage_denies_install(self):
        action=self.fixture(short=True); root,files=self.files(); adapter,key=self.prepare(action,files)
        result=adapter.step(action['action_id'],'write',key,
            lambda point:self.wait_expiry(action) if point=='staged' else None)
        self.assertEqual(result['state'],'unknown'); self.assertFalse(self.target(root,action).exists())
        self.assertEqual(adapter.step(action['action_id'],'reconcile','expired-'+uuid4().hex)['state'],'cancelled')
    def test_native_pause_after_final_authorization_diagnostic_not_safety_pass(self):
        # Known counterexample: a successful test CONFIRMS an activation blocker.
        action=self.fixture(short=True); root,files=self.files(); adapter,key=self.prepare(action,files)
        original=files.publish
        def paused(case,content,digest,authorize,checkpoint=None):
            calls=[0]
            def check():
                allowed=authorize(); calls[0]+=1
                if calls[0]==2 and allowed: self.wait_expiry(action)
                return allowed
            return original(case,content,digest,check,checkpoint)
        files.publish=paused
        result=adapter.step(action['action_id'],'write',key)
        self.assertEqual(result['state'],'succeeded')
        self.assertTrue(self.target(root,action).exists())
        self.assertFalse(state(CONFIG,action)['write_allowed'])
    def test_native_zz_revocation_after_claim_denies_file_write(self):
        action=self.fixture(); root,files=self.files(); adapter,key=self.prepare(action,files)
        def revoke(point):
            if point=='claim_committed': self.controller.call('revoke')
        result=adapter.step(action['action_id'],'write',key,revoke)
        self.assertEqual(result['state'],'unknown'); self.assertFalse((root/'reports').exists())
        self.assertEqual(adapter.step(action['action_id'],'reconcile','revoked-'+uuid4().hex)['state'],'cancelled')


def run(config,native=False):
    global CONFIG
    CONFIG=config
    cls=NativeTests if native else BridgeTests
    if native and os.name!='nt': raise RuntimeError('Native Windows owner run required')
    class PrivateResult(unittest.TextTestResult):
        types=[]
        def addError(self,test,error): self.types.append(error[0].__name__); super().addError(test,error)
    result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=PrivateResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    return {'passed':result.wasSuccessful(),'tests_run':result.testsRun,
        'failed_tests':[getattr(t,'_testMethodName','class_setup') for t,_ in result.errors+result.failures],
        'error_types':result.types,'evidence':'native-NTFS-real-SQL' if native else 'IPC-real-SQL-memory-files-NOT-NTFS',
        'activation_blocked':True}


if __name__=='__main__':
    try:
        value=json.loads(sys.stdin.read())
        root=value.get('root')
        if root:
            path=Path(root).resolve(); base=(ROOT/'.local'/'wp4-publication-tests').resolve()
            if path.parent!=base or not path.name.startswith('dispatch-'): raise ValueError('Synthetic root required')
            files=WindowsPublicationFiles(path)
        else: files=MemoryFiles()
        if value['crash'] not in ('claim_committed','staged','installed','receipt_pending','receipt_committed'):
            raise ValueError('Fixed crash point required')
        dispatcher(value,files).step(value['action'],'write',value['key'],
            lambda point:os._exit(77) if point==value['crash'] else None)
        print('{"failed":"crash-not-reached"}')
        raise SystemExit(1)
    except Exception:
        print('{"failed":"synthetic-child-denied"}')
        raise SystemExit(1) from None
