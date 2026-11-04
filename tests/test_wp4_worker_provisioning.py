"""Mocked mode routing; never accesses Docker, credentials or private registry."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import check_wp4_portal_publication_local as helper


class ProvisioningModes(unittest.TestCase):
    def run_mode(self,**mode):
        config={'database':'raa_wp4_dispatch_test_aaaaaaaaaaaa',
                'worker':{'user':'raa_wp4_dispatch_test_bbbbbbbbbbbb','password':'1'*64}}
        with patch.object(helper,'provision',return_value=config),patch.object(helper,'docker',return_value='') as docker,\
             patch.object(helper,'retain'),patch.object(helper,'retain_many'),patch.object(helper.secrets,'token_hex',return_value='a'*64),\
             patch('builtins.print'):
            result=helper.provision_portal(**mode)
        return result, [c.args[1] for c in docker.call_args_list if len(c.args)>1]

    def test_auth_does_not_grant_worker_or_require_migration_028(self):
        config,sql=self.run_mode(auth=True)
        self.assertIn('auth',config); self.assertNotIn('portal_worker',config)
        self.assertFalse(any('api_worker_portal_state_v2' in s for s in sql))

    def test_reads_does_not_activate_auth_or_worker_mode(self):
        config,sql=self.run_mode(reads=True)
        self.assertIn('reader',config); self.assertNotIn('auth',config); self.assertNotIn('portal_worker',config)
        self.assertFalse(any('api_portal_auth_login_v2' in s or 'api_worker_portal_state_v2' in s for s in sql))

    def test_worker_includes_required_auth_and_exact_worker_grants(self):
        config,sql=self.run_mode(worker=True)
        self.assertIn('auth',config); self.assertIn('portal_worker',config)
        self.assertTrue(any('api_worker_portal_state_v2' in s for s in sql))
        self.assertIn('api_worker_accept_portal_v2(uuid,text,uuid,text,text)',sql[-1])

    def test_attempts_adds_separate_worker_recovery_without_old_worker_grant_expansion(self):
        config,sql=self.run_mode(attempts=True)
        self.assertIn('attempt_worker',config); self.assertIn('recovery',config)
        self.assertTrue(any('portal_worker_events_v1' in s for s in sql))
        self.assertIn('api_accept_portal_attempt_v1(uuid,text,uuid,text)',sql[-1])
        self.assertIn('api_operator_reconcile_portal_v1(uuid,text,text)',sql[-1])
        _,oldsql=self.run_mode(worker=True)
        self.assertFalse(any('portal_worker_events_v1' in s or 'api_accept_portal_attempt_v1' in s for s in oldsql))

    def test_attempt_api_adds_only_isolated_tokens_and_preserves_sql_modes(self):
        config,sql=self.run_mode(attempt_api=True)
        self.assertIn('attempt_worker',config); self.assertIn('recovery',config)
        self.assertIn('attempt_token',config); self.assertIn('recovery_token',config)
        old,_=self.run_mode(attempts=True)
        self.assertNotIn('attempt_token',old); self.assertNotIn('recovery_token',old)
        self.assertIn('api_operator_reconcile_portal_v1(uuid,text,text)',sql[-1])


if __name__=='__main__':
    unittest.main()
