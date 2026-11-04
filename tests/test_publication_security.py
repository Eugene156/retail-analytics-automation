"""Synthetic leak/invalid-export checks; no credential or runtime access."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_publication as check


class PublicationSecurityTests(unittest.TestCase):
    def inspect_json(self, value, secrets=()):
        with patch.object(Path, 'read_bytes', return_value=json.dumps(value).encode()):
            return check.inspect('workflows/demo.json', secrets)

    def test_staged_ignored_paths_are_rejected(self):
        for path in ('.local/token', 'credentials/c.json', 'data/raw/source.csv',
                     'sessions/user.json', 'evidence/private/result.json',
                     'evidence/demo.png', '.codex/config.toml', 'db.snapshot.dump'):
            self.assertIsNotNone(check.inspect(path, ()))

    def test_known_secret_is_rejected_even_under_public_filename(self):
        secret = b'synthetic-secret-value-for-test'
        self.assertEqual(self.inspect_json({'description': secret.decode()}, [secret]),
                         'secret detected')

    def test_raw_execution_and_pinned_data_are_rejected(self):
        self.assertEqual(self.inspect_json({'data': {'runData': {}}}), 'raw execution data')
        self.assertEqual(self.inspect_json({'pinData': {'SQL': [{}]}}), 'pinned workflow data')

    def test_credential_reference_is_allowed(self):
        self.assertIsNone(self.inspect_json({'nodes': [{'credentials': {
            'httpHeaderAuth': {'id': 'demo-read', 'name': 'Demo read only'}}}]}))

    def test_plaintext_authentication_header_is_rejected(self):
        self.assertEqual(self.inspect_json({'nodes': [{'parameters': {
            'Authorization': 'Bearer ' + 'x' * 32}}]}), 'literal authentication header')

    def test_invalid_python_is_rejected(self):
        with patch.object(Path, 'read_bytes', return_value=b'def broken(:'):
            with self.assertRaises(SyntaxError):
                check.inspect('scripts/example.py', ())


if __name__ == '__main__':
    unittest.main()
