"""Offline source/contract tests, never native custody or business-hook evidence."""
import ast
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wp4_custody_coverage_contract as c


class CustodyCoverageTests(unittest.TestCase):
    def test_frozen_49_functions_14_roles_52_bindings_19_mutators(self):
        result=c.check_plan(c.planned_contract())
        for key,value in dict(functions=49,roles=14,bindings=52,mutators=19,planned_scenarios=14).items():
            self.assertEqual(result[key],value)
        for key in ('native_execution_proved','runtime_start_allowed','application_writers_admitted'):
            self.assertIs(result[key],False)

    def test_all_reads_and_mutators_guarded_no_implemented_claim(self):
        for row in c.planned_contract()['routes'].values():
            self.assertEqual(row['guard'],'same-transaction-before-business')
            self.assertEqual(row['closed'],'deny');self.assertIs(row['implemented'],False)
            self.assertTrue(row['roles'])

    def test_server_identity_not_caller_uuid_or_definer_owner(self):
        custody=c.planned_contract()['custody']
        self.assertEqual(set(custody['server_fields']),set(c.SERVER_FIELDS))
        self.assertNotIn('current_user',custody['server_fields'])
        self.assertNotIn('caller_uuid',custody['server_fields'])
        for field in ('takeover','old004_close_execute','caller_identity_authoritative',
                      'authenticated_runtime_identity_verified'):
            self.assertIs(custody[field],False)
        self.assertTrue(custody['persistent_connection'])

    def test_each_scenario_fact_mutation_rejected(self):
        for name,facts in c.CASES.items():
            for key,value in facts.items():
                plan=c.planned_contract();plan['scenarios'][name][key]=not value
                with self.subTest(name=name,key=key),self.assertRaises(c.CoverageDenied):c.check_plan(plan)

    def test_each_missing_extra_or_unguarded_route_denied(self):
        for signature in c.routes():
            plan=c.planned_contract();plan['routes'].pop(signature)
            with self.assertRaises(c.CoverageDenied):c.check_plan(plan)
            plan=c.planned_contract();plan['routes'][signature]['guard']='app-preflight'
            with self.assertRaises(c.CoverageDenied):c.check_plan(plan)
        plan=c.planned_contract();plan['routes']['unknown()']={}
        with self.assertRaises(c.CoverageDenied):c.check_plan(plan)

    def test_exact_types_no_native_or_runtime_relabelling(self):
        for key,value in (('native_scenarios_executed',False),('native_scenarios_executed',14),
                          ('runtime_start_allowed',1),('runtime_start_allowed',True),
                          ('evidence_status','verified-in-current-environment'),('scope','main')):
            plan=c.planned_contract();plan[key]=value
            with self.assertRaises(c.CoverageDenied):c.check_plan(plan)

    def test_plan_export_does_not_mutate_reference(self):
        plan=c.planned_contract();plan['custody']['server_fields'].clear()
        plan['routes'].clear();plan['scenarios']['owner-backend-gone']['takeover']=True
        self.assertEqual(c.check_plan(c.planned_contract())['functions'],49)

    def test_source_projection_is_not_native_acl_or_guard_proof(self):
        result=c.audit_sources()
        self.assertTrue(result['source_projection_verified']);self.assertEqual(result['functions'],49)
        self.assertEqual(result['quarantined_dispatch_names'],4)
        for key in ('effective_native_acl_verified','guard_implementation_verified','runtime_start_allowed'):
            self.assertIs(result[key],False)

    def test_changed_scope_cannot_auto_extend_coverage(self):
        files=c.source_files()
        files['api/populated_deployment.py']=files['api/populated_deployment.py'].replace(
            "'api_portal_identity_v1(text)'","'api_unreviewed(text)'",1)
        with self.assertRaises(c.CoverageDenied):c.audit_sources(files)

    def test_added_portal_grant_or_role_denied(self):
        files=c.source_files();path='db/deployment/002_portal_schema_rehearsal.sql'
        for grant in ('GRANT EXECUTE ON FUNCTION retail.api_unreviewed(text) TO raa_wp4_portal_read_v2;',
                      'GRANT EXECUTE ON FUNCTION retail.api_portal_identity_v1(text) TO unexpected_role;'):
            bad=dict(files);bad[path]=files[path]+'\n'+grant
            with self.assertRaises(c.CoverageDenied):c.audit_sources(bad)

    def test_retired_prepare_api_stays_revoked(self):
        files=c.source_files();path='db/migrations/017_explicit_approval_requests.sql'
        files[path]=files[path].replace('REVOKE EXECUTE ON FUNCTION retail.api_prepare_approval_proposal_v1(uuid,integer,text) FROM raa_wp2_case_api;','')
        with self.assertRaises(c.CoverageDenied):c.audit_sources(files)
        self.assertNotIn('api_prepare_approval_proposal_v1(uuid,integer,text)',c.routes())

    def test_missing_original_function_grant_denied(self):
        files=c.source_files();path='db/migrations/012_comparison_api_boundary.sql'
        files[path]=files[path].replace('GRANT EXECUTE','REVOKE EXECUTE').replace('TO raa_wp2_api','FROM raa_wp2_api')
        with self.assertRaises(c.CoverageDenied):c.audit_sources(files)

    def test_unreviewed_api_call_name_fails_closed(self):
        files=c.source_files();files['api/main.py']+='\n# SELECT retail.api_unreviewed()\n'
        with self.assertRaises(c.CoverageDenied):c.audit_sources(files)

    def test_ntfs_dispatch_cannot_move_into_main_or_owner_surface(self):
        for path in ('api/main.py','api/portal.py'):
            files=c.source_files();files[path]+='\n# SELECT retail.api_claim_publication_v1()\n'
            with self.assertRaises(c.CoverageDenied):c.audit_sources(files)

    def test_added_application_file_requires_explicit_review(self):
        with patch.object(Path,'glob',return_value=[Path(name) for name in (*c.APPS,'new_unreviewed.py')]):
            with self.assertRaises(c.CoverageDenied):c.source_files()

    def test_missing_extra_source_or_secret_field_finite_error(self):
        files=c.source_files();missing=dict(files);missing.pop('api/main.py')
        for bad in (missing,dict(files,password='do-not-display'),dict(files,**{'api/new.py':''})):
            with self.assertRaises(c.CoverageDenied) as error:c.audit_sources(bad)
            self.assertEqual(str(error.exception),'Custody coverage contract denied')

    def test_literal_acl_subset_refuses_wrong_direction_or_unrecognised_items(self):
        for source in ('GRANT EXECUTE ON FUNCTION retail.x(text) FROM role;',
                       'GRANT EXECUTE ON FUNCTION other.x(text) TO role;',
                       'REVOKE EXECUTE ON FUNCTION retail.x(text) FROM role;'):
            with self.assertRaises(c.CoverageDenied):c.acl_projection([source])
        result=c.acl_projection(['GRANT EXECUTE ON FUNCTION retail.x(text, uuid) TO role;',
                                'REVOKE EXECUTE ON FUNCTION retail.x(text,uuid) FROM role;'])
        self.assertEqual(result,{'role':()})

    def test_only_stdlib_imports_no_executor_or_app_main_hook(self):
        tree=ast.parse(Path(c.__file__).read_text())
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        self.assertLessEqual(imports,{'ast','copy','pathlib','re','sys'})
        self.assertNotIn('custody_coverage_contract',(c.ROOT/'api/main.py').read_text())
        self.assertEqual(c.planned_contract()['guard']['transaction_mode'],'read write')
        self.assertFalse(c.planned_contract()['guard']['rename_original'])

    def test_standalone_cli_success_deliberately_blocked_exit_two(self):
        result=subprocess.run([sys.executable,c.__file__],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertIn('49-functions|52-bindings|native-not-run',result.stdout)
        self.assertIn('BLOCKED|runtime-admission',result.stdout)

    def test_cli_rejects_live_target_or_other_argument(self):
        for argument in ('--live','--native','raa_wp2_validation'):
            result=subprocess.run([sys.executable,c.__file__,argument],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,1);self.assertIn('no-target-or-live-option',result.stdout)


if __name__=='__main__':unittest.main()
