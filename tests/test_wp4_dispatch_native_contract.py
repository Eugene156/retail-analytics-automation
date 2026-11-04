"""Pure native-harness path contracts. No file handles, DB or subprocesses."""
import importlib.util
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from api.publication_dispatch import DispatchBindingError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('native_harness_contract',ROOT/'tests/wp4_dispatch_native_suite.py')
native=importlib.util.module_from_spec(spec); spec.loader.exec_module(native)


class NativeFixtureContracts(unittest.TestCase):
    def setUp(self):
        self.case=str(uuid4())
        self.root=Path(r'C:\synthetic\private')
        # Migration 019 decision_snapshot_v1.outbox deliberately has no case_id.
        self.action={'action_id':str(uuid4()),'action_key':'synthetic-action','state':'pending',
            'target_id':'local-approved-report-json-v1',
            'relative_path':f'reports/approved/v1/{self.case}/revision-1.json',
            'content_sha256':'0'*64,'content_bytes':42,'action_payload_sha256':'1'*64,
            'authorization_expires_at':'2026-10-05T12:00:00+00:00'}
        self.test=native.NativeTests('test_native_exact_bytes_ten_replays_no_rewrite')

    def test_real_outbox_shape_without_case_id_maps_exact_fixed_target(self):
        self.assertNotIn('case_id',self.action)
        self.assertEqual(self.test.target(self.root,self.action),
            self.root/'reports'/'approved'/'v1'/self.case/'revision-1.json')

    def test_unrelated_case_id_is_not_used_as_an_unbound_path_override(self):
        self.action['case_id']='../outside'
        self.assertEqual(self.test.target(self.root,self.action),
            self.root/'reports'/'approved'/'v1'/self.case/'revision-1.json')

    def test_wrong_target_id_is_denied(self):
        self.action['target_id']='other-target'
        with self.assertRaises(DispatchBindingError): self.test.target(self.root,self.action)

    def test_missing_and_nontext_paths_are_denied_safely(self):
        for path in (None,42,''):
            self.action['relative_path']=path
            with self.assertRaises(DispatchBindingError): self.test.target(self.root,self.action)
        del self.action['relative_path']
        with self.assertRaises(DispatchBindingError): self.test.target(self.root,self.action)

    def test_traversal_absolute_stream_and_alternate_revision_denied(self):
        for path in ('../outside',r'C:\outside',f'/reports/approved/v1/{self.case}/revision-1.json',
                f'reports/approved/v1/{self.case}/revision-2.json',
                f'reports/approved/v1/{self.case}/revision-1.json:stream',
                f'reports/approved/v1/{self.case}/../revision-1.json',
                f'reports/approved/v1/{self.case}/extra/revision-1.json',
                f'reports//approved/v1/{self.case}/revision-1.json'):
            self.action['relative_path']=path
            with self.subTest(path=path):
                with self.assertRaises(DispatchBindingError): self.test.target(self.root,self.action)

    def test_noncanonical_case_path_denied(self):
        for case in (self.case.upper(),'not-a-uuid',self.case+':stream'):
            self.action['relative_path']=f'reports/approved/v1/{case}/revision-1.json'
            with self.assertRaises(DispatchBindingError): self.test.target(self.root,self.action)


if __name__=='__main__': unittest.main()
