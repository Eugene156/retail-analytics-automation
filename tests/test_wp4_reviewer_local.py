"""Private-file/helper mocks, not live identity or HTTP proof."""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import wp4_reviewer_local as local


class LocalReviewerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.config=root/"config"
        self.owner=root/"owner"
        self.config.mkdir()
        self.owner.mkdir()
        self.service=secrets.token_hex(32)
        (self.config/"token").write_text(self.service,encoding="utf-8")
        for name,value in (("SECRET_DIR",self.config),("OWNER_DIR",self.owner),
                           ("CREDENTIAL",self.owner/"credential.json"),("DSN",self.config/"reviewer-dsn")):
            p=patch.object(local,name,value)
            p.start()
            self.addCleanup(p.stop)

    def save(self,token=None):
        credential={"reviewer_id":str(uuid4()),"token":token or secrets.token_hex(32)}
        local.CREDENTIAL.write_text(json.dumps(credential),encoding="utf-8")
        local.DSN.write_text("postgresql://raa_wp4_reviewer_api:"+secrets.token_hex(32)
            +"@raa-g0-postgres-1:5432/raa_wp2_validation",encoding="utf-8")
        return credential

    def test_separate_token_and_digest_are_in_privacy_scan(self):
        credential=self.save()
        from hashlib import sha256
        values=local.secret_values()
        self.assertTrue(credential["token"] in values)
        self.assertTrue(sha256(credential["token"].encode()).hexdigest() in values)
        self.save(self.service)
        with self.assertRaises(ValueError): local.credentials()

    def test_bootstrap_replay_preserves_files_and_does_not_pass_secrets_in_argv(self):
        self.save()
        before=(local.CREDENTIAL.read_bytes(),local.DSN.read_bytes())
        with patch.object(local,"docker",side_effect=["t",""]) as docker, patch("builtins.print"):
            local.bootstrap()
        self.assertEqual(before,(local.CREDENTIAL.read_bytes(),local.DSN.read_bytes()))
        argv,stdin=docker.call_args.args
        self.assertTrue("-i" in argv)
        self.assertTrue("86400" in stdin)
        self.assertTrue("revoked_at IS NOT NULL" in stdin)
        self.assertTrue(all(secret not in " ".join(argv) for secret in local.secret_values()))

    def test_partial_configuration_and_unknown_existing_mapping_are_not_overwritten(self):
        self.save()
        original=local.CREDENTIAL.read_bytes()
        local.DSN.unlink()
        with patch.object(local,"docker",return_value="t"), self.assertRaises(RuntimeError): local.bootstrap()
        self.assertEqual(local.CREDENTIAL.read_bytes(),original)
        local.CREDENTIAL.unlink()
        with patch.object(local,"docker",side_effect=["t","f"]), self.assertRaises(RuntimeError): local.bootstrap()
        self.assertFalse(local.CREDENTIAL.exists())
        self.assertFalse(local.DSN.exists())

    def test_new_configuration_is_generated_only_after_empty_database_guard(self):
        with patch.object(local,"docker",side_effect=["t","t",""]), patch("builtins.print"):
            local.bootstrap()
        value=local.credentials()
        self.assertTrue(value["token"] != self.service)
        self.assertEqual(len(local.secret_values()),5)


if __name__ == "__main__": unittest.main()
