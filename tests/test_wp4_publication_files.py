"""Actual Windows filesystem tests on isolated project-local synthetic targets."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from uuid import uuid4
from api.local_publication import (WindowsPublicationFiles,UnsafeTarget,TargetConflict,
    PublicationBusy,AuthorizationDenied,PublicationUnknown)

ROOT=Path(__file__).resolve().parents[1]
BODY=b'{"synthetic_test":true,"decimal_text":"1349.4500000000000000"}'
HASH=sha256(BODY).hexdigest()


@unittest.skipUnless(os.name=='nt','Native Windows/NTFS test required')
class PublicationFileTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.local'/'wp4-publication-tests'
        base.mkdir(parents=True,exist_ok=True)
        # Keep generated fixtures for evidence; no recursive deletion or cleanup
        # against a project/source tree and no real reports/approved write.
        self.root=Path(tempfile.mkdtemp(prefix='files-',dir=base))
        self.case=str(uuid4())
        self.files=WindowsPublicationFiles(self.root)
        self.target=self.root/'reports'/'approved'/'v1'/self.case/'revision-1.json'

    def test_create_exact_bytes_ten_replays_and_readonly_reconciliation(self):
        self.assertEqual(self.files.reconcile(self.case,BODY,HASH),'missing')
        self.assertEqual(self.files.publish(self.case,BODY,HASH,lambda:True),'created')
        original=self.target.stat()
        for _ in range(10):
            self.assertEqual(self.files.publish(self.case,BODY,HASH,lambda:True),'reconciled')
        self.assertEqual(self.target.read_bytes(),BODY)
        self.assertEqual(self.target.stat().st_mtime_ns,original.st_mtime_ns)
        self.assertEqual(self.files.reconcile(self.case,BODY,HASH),'matching')
        # A single favorable allocation must not hide an unterminated rename
        # buffer. Check repeated fresh targets and their exact final filenames.
        for _ in range(25):
            case=str(uuid4())
            self.assertEqual(self.files.publish(case,BODY,HASH,lambda:True),'created')
            target=self.target.parent.parent/case/'revision-1.json'
            self.assertEqual(target.read_bytes(),BODY)
            self.assertEqual([p.name for p in target.parent.iterdir()],['revision-1.json'])

    def test_invalid_bindings_paths_and_size_never_write(self):
        for case in ('../outside',self.case.upper(),'C:\\elsewhere',self.case+':stream'):
            with self.assertRaises(UnsafeTarget): self.files.publish(case,BODY,HASH,lambda:True)
        for content,hash_value in ((BODY,'0'*64),(b'',HASH),(b'x'*131073,HASH),(BODY.decode(),HASH)):
            with self.assertRaises(TargetConflict): self.files.publish(self.case,content,hash_value,lambda:True)
        self.assertFalse((self.root/'reports').exists())

    def test_authorization_denied_before_stage_or_before_install(self):
        with self.assertRaises(AuthorizationDenied): self.files.publish(self.case,BODY,HASH,lambda:False)
        self.assertFalse((self.root/'reports').exists())
        values=iter([True,False])
        with self.assertRaises(AuthorizationDenied): self.files.publish(self.case,BODY,HASH,lambda:next(values))
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.target.parent.glob('.staged-*')),[])

    def test_different_existing_file_not_overwritten(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'other synthetic bytes')
        for method in (self.files.publish,self.files.reconcile):
            with self.assertRaises(TargetConflict):
                args=(self.case,BODY,HASH,lambda:True) if method==self.files.publish else (self.case,BODY,HASH)
                method(*args)
        self.assertEqual(self.target.read_bytes(),b'other synthetic bytes')

    def test_hardlink_target_denied(self):
        self.target.parent.mkdir(parents=True)
        original=self.root/'original.json'; original.write_bytes(BODY)
        os.link(original,self.target)
        with self.assertRaisesRegex(UnsafeTarget,'Reparse point or aliased target denied'):
            self.files.publish(self.case,BODY,HASH,lambda:True)
        self.assertEqual(original.read_bytes(),BODY)

    def test_directory_junction_denied_without_outside_write(self):
        outside=self.root/'outside'; outside.mkdir()
        junction=self.root/'reports'
        # Fixed quoted paths under this test's validated root only; no delete/move.
        result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True)
        self.assertEqual(result.returncode,0)
        with self.assertRaisesRegex(UnsafeTarget,'Reparse point or aliased target denied'):
            self.files.publish(self.case,BODY,HASH,lambda:True)
        self.assertEqual(list(outside.iterdir()),[])

    def test_held_ancestor_cannot_be_renamed(self):
        outcomes=[]
        def checkpoint(stage):
            if stage=='staged':
                try: self.target.parent.rename(self.target.parent.with_name(self.case+'-moved'))
                except OSError: outcomes.append('denied')
                else: outcomes.append('unexpected')
        self.files.publish(self.case,BODY,HASH,lambda:True,checkpoint)
        self.assertEqual(outcomes,['denied'])
        self.assertEqual(self.target.read_bytes(),BODY)

    def test_held_stage_cannot_be_modified(self):
        outcomes=[]
        def checkpoint(stage):
            if stage=='staged':
                staged=next(self.target.parent.glob('.staged-*'))
                try: staged.write_bytes(b'tampered')
                except OSError: outcomes.append('denied')
                else: outcomes.append('unexpected')
        self.files.publish(self.case,BODY,HASH,lambda:True,checkpoint)
        self.assertEqual(outcomes,['denied']); self.assertEqual(self.target.read_bytes(),BODY)

    def test_two_concurrent_writers_single_exact_target(self):
        barrier=threading.Barrier(2)
        def work():
            files=WindowsPublicationFiles(self.root); barrier.wait(timeout=5)
            for attempt in range(3):
                try: return files.publish(self.case,BODY,HASH,lambda:True)
                except (PublicationBusy,PublicationUnknown):
                    # Reconcile BEFORE any second write attempt.
                    time.sleep(.1)
                    try:
                        if files.reconcile(self.case,BODY,HASH)=='matching': return 'reconciled'
                    except PublicationBusy: pass
                    if attempt==2: raise
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:work(),range(2)))
        self.assertEqual(outcomes.count('created'),1)
        self.assertEqual(outcomes.count('reconciled'),1)
        self.assertEqual(self.target.read_bytes(),BODY)

    def crash(self,stage):
        code=("import os; from api.local_publication import WindowsPublicationFiles; "
            "from hashlib import sha256; from pathlib import Path; import sys; "
            "body="+repr(BODY)+"; "
            "WindowsPublicationFiles(Path(sys.argv[1])).publish(sys.argv[2],body,sha256(body).hexdigest(),"
            "lambda:True,lambda step:os._exit(77) if step==sys.argv[3] else None)")
        result=subprocess.run([sys.executable,'-c',code,str(self.root),self.case,stage],cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,77)

    def test_actual_process_crash_before_install_never_promotes_stage(self):
        self.crash('staged')
        self.assertFalse(self.target.exists())
        self.assertEqual(self.files.reconcile(self.case,BODY,HASH),'missing')
        self.assertEqual(len(list(self.target.parent.glob('.staged-*'))),1)
        self.assertEqual(self.files.publish(self.case,BODY,HASH,lambda:True),'created')
        self.assertEqual(self.target.read_bytes(),BODY)

    def test_actual_process_crash_after_install_reconciles_without_rewrite(self):
        self.crash('installed')
        before=self.target.stat().st_mtime_ns
        self.assertEqual(self.files.reconcile(self.case,BODY,HASH),'matching')
        self.assertEqual(self.files.publish(self.case,BODY,HASH,lambda:True),'reconciled')
        self.assertEqual(self.target.stat().st_mtime_ns,before)


if __name__=='__main__': unittest.main()
