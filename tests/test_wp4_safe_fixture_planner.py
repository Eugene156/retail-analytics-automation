"""I2 offline generation; no database/restore/external integration claims."""
from dataclasses import replace
from hashlib import sha256
import io
import gzip
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wp4_safe_fixture_planner as p
import wp4_safe_fixture_recipe as files
import wp4_safe_fixture_contract as i1

KEY='42b4d3b2-98d8-4d0f-a7fd-25c3c66466ad'


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.inputs=files.load_inputs()
        self.context=i1.ScopedContext.from_contract(i1.canonical(i1.proposal(KEY)),'source-build')
        self.reference=i1.ScopedContext.from_contract(i1.canonical(i1.proposal(KEY)),'reference-build')
        self.counts=(('Year 2009-2010',2),('Year 2010-2011',1))
        cells=[['str','same public value'] for _ in range(8)]
        self.rows=[['Year 2009-2010',2,cells],['Year 2009-2010',3,cells],['Year 2010-2011',2,cells]]

    def render(self,rows=None):
        with patch.object(p,'SHEETS',self.counts):
            return b''.join(p.import_chunks(self.context,self.inputs,self.rows if rows is None else rows,self.counts))

    def test_recipe_reproduction_source_reference_and_non_admission(self):
        raw=i1.canonical(p.recipe(self.context,self.inputs))
        self.assertEqual(p.validate_recipe(raw,self.context,self.inputs),sha256(raw).hexdigest())
        self.assertEqual(raw,p.CapturePlanner(self.context,self.inputs).document())
        reference=p.recipe(self.reference,self.inputs)
        actions=[s['action'] for s in reference['steps']]
        self.assertLess(actions.index('apply-021-verbatim'),actions.index('disconnect-and-guarded-reference-rename'))
        self.assertLess(actions.index('disconnect-and-guarded-reference-rename'),actions.index('apply-022-029-verbatim'))
        self.assertTrue(all(s['status']=='not-run' for s in reference['steps']))
        for method in (lambda:p.CapturePlanner(self.context,self.inputs).execute(),
                       lambda:p.CapturePlanner(self.context,self.inputs).accept_native_evidence({'catalog':True})):
            with self.assertRaises(p.PlannerDenied):method()

    def test_tampered_hash_mapping_evidence_step_order_denied(self):
        for field in ('inputs','mapping','steps','native_evidence_acquired'):
            record=p.recipe(self.context,self.inputs);record[field]=True
            with self.assertRaises(p.PlannerDenied):p.validate_recipe(i1.canonical(record),self.context,self.inputs)

    def test_source_migrations20_reference29_complete_guards(self):
        self.assertEqual(len(p.migration_batches(self.context,self.inputs)),20)
        reference=p.migration_batches(self.reference,self.inputs);self.assertEqual(len(reference),29)
        for (name,body),(actual,wrapped) in zip(self.inputs.migrations,reference):
            self.assertEqual(name,actual);self.assertIn(body,wrapped)
        self.assertIn(b"current_database()<>'raa_wp2_validation'",reference[20][1])
        self.assertIn(b"^raa_wp4_dispatch_test_[a-f0-9]{12}$",reference[21][1])

    def test_import_reproduction_physical_duplicates_and_fk_job(self):
        first=self.render();self.assertEqual(first,self.render())
        self.assertIn(b'Year 2009-2010,2,',first);self.assertIn(b'Year 2009-2010,3,',first)
        self.assertIn(i1.mappings(KEY)['fresh']['import-job'].encode(),first)
        self.assertIn(self.inputs.finalize,first);self.assertIn(b'classify_snapshot_v1',first)

    def test_csv_untrusted_cells_cannot_break_sql(self):
        rows=json.loads(json.dumps(self.rows));rows[0][2][0][1]='\n\\.\n";DROP TABLE retail.source_rows;--'
        data=self.render(rows)
        # Values are JSON strings inside CSV; no physical COPY terminator injected.
        self.assertEqual(data.count(b'\n\\.\n'),4)
        self.assertIn(b'\\n',data)

    def test_missing_extra_duplicate_wrong_sheet_bool_row_denied(self):
        bad=[self.rows[:-1],self.rows+[None],self.rows+[self.rows[-1]],
             [self.rows[0],self.rows[0],self.rows[2]], [['external',2,self.rows[0][2]],*self.rows[1:]],
             [['Year 2009-2010',True,self.rows[0][2]],*self.rows[1:]]]
        for rows in bad:
            with self.assertRaises(p.PlannerDenied):self.render(rows)

    def test_wrong_context_inputs_external_path_and_source_limit(self):
        rehearsal=i1.ScopedContext.from_contract(i1.canonical(i1.proposal(KEY)),'rehearsal')
        with self.assertRaises(p.PlannerDenied):p.recipe(rehearsal,self.inputs)
        for inputs in (replace(self.inputs,migrations=self.inputs.migrations[:-1]),
            replace(self.inputs,migrations=(('../external.sql',b'fixture'),)+self.inputs.migrations[1:]),
            replace(self.inputs,finalize=b'')):
            with self.assertRaises(p.PlannerDenied):p.recipe(self.context,inputs)
        with self.assertRaises(p.PlannerDenied):p.reference_database(self.context)

    def test_native_report_not_offline_candidate_and_no_secret_rendering(self):
        sql=p.report_alias_sql(self.context,self.inputs)
        self.assertIn(i1.LEGACY_CASE.encode(),sql);self.assertIn(b'api_finish_report_v1',sql)
        self.assertIn(i1.SOURCE['report_sha256'].encode(),sql);self.assertIn(b'octet_length(body)<>4129',sql)
        self.assertIn(b'api_get_revision_v1',sql);self.assertNotIn(b'owner_credentials',sql)

    def test_no_environment_subprocess_or_native_credential_minting(self):
        import os,subprocess,secrets
        with patch.object(os,'getenv',side_effect=AssertionError('environment forbidden')),\
             patch.object(subprocess,'run',side_effect=AssertionError('native forbidden')),\
             patch.object(secrets,'token_bytes',side_effect=AssertionError('minting forbidden')):
            p.recipe(self.context,self.inputs);self.render();p.report_alias_sql(self.context,self.inputs)

    def test_consumed_source_is_immutable_even_if_path_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            public=Path(folder);data=gzip.compress(b'{"public":true}\n',mtime=0)
            path=public/'public-rows.jsonl.gz';path.write_bytes(data)
            record={'artifacts':{'public-rows.jsonl.gz':{'bytes':len(data),'sha256':sha256(data).hexdigest()}}}
            original=gzip.GzipFile
            def substituted(*args,**kwargs):
                path.write_bytes(gzip.compress(b'{"forged":true}\n',mtime=0))
                return original(*args,**kwargs)
            with patch.object(files,'PUBLIC',public),patch.object(files,'validate_public',return_value=record),\
                 patch.object(gzip,'GzipFile',side_effect=substituted):
                self.assertEqual(list(files.public_rows()),[{'public':True}])

    def test_wrong_consumed_source_hash_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            public=Path(folder);(public/'public-rows.jsonl.gz').write_bytes(b'wrong')
            record={'artifacts':{'public-rows.jsonl.gz':{'bytes':5,'sha256':'0'*64}}}
            with patch.object(files,'PUBLIC',public),patch.object(files,'validate_public',return_value=record):
                with self.assertRaises(p.PlannerDenied):list(files.public_rows())

    def test_export_reproduction_closed_inventory_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(files,'load_inputs',return_value=self.inputs),\
             patch.object(files,'validate_public',return_value={}),patch.object(p,'SHEETS',self.counts),\
             patch.object(files,'public_rows',side_effect=lambda:iter(self.rows)),patch('builtins.print'):
            snapshots=[]
            for name in ('first','second'):
                output=Path(folder)/name
                with patch.object(files,'OUTPUT',output):
                    self.assertEqual(files.export(),2)
                    with self.assertRaises(p.PlannerDenied):files.export()
                snapshots.append({f.relative_to(output).as_posix():f.read_bytes() for f in output.rglob('*') if f.is_file()})
            self.assertEqual(snapshots[0],snapshots[1]);self.assertEqual(len(snapshots[0]),55)

    def test_export_rejects_extra_changed_or_linked_output_without_manifest(self):
        original=files.seal_inventory
        for mode in ('extra','changed','link'):
            with tempfile.TemporaryDirectory() as folder,patch.object(files,'load_inputs',return_value=self.inputs),\
                 patch.object(files,'validate_public',return_value={}),patch.object(p,'SHEETS',self.counts),\
                 patch.object(files,'public_rows',side_effect=lambda:iter(self.rows)):
                output=Path(folder)/'output'
                def tamper(artifacts):
                    target=output/'public-import.sql'
                    if mode=='extra':(output/'unknown.bin').write_bytes(b'unplanned')
                    elif mode=='changed':target.write_bytes(b'changed')
                    if mode=='link':
                        real=files.no_links
                        def deny(path):
                            p.require(path!=target);real(path)
                        with patch.object(files,'no_links',side_effect=deny):return original(artifacts)
                    return original(artifacts)
                with patch.object(files,'OUTPUT',output),patch.object(files,'seal_inventory',side_effect=tamper):
                    with self.assertRaises(p.PlannerDenied):files.export()
                self.assertFalse((output/'manifest.json').exists())


if __name__=='__main__':unittest.main()
