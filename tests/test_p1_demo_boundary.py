"""Offline denial checks; these do not prove Docker or end-to-end execution."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('p1_demo', Path(__file__).resolve().parents[1] / 'scripts/p1_demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoBoundaryTests(unittest.TestCase):
    def test_foreign_project_is_denied_before_sql(self):
        with patch.object(demo, 'docker', return_value=json.dumps({
                'com.docker.compose.project': 'raa-g0', 'com.docker.compose.service': 'postgres'})) as command:
            with self.assertRaisesRegex(RuntimeError, 'demo-postgres-ownership'):
                demo.guard()
            self.assertEqual(command.call_count, 1)

    def test_historical_volume_is_denied_even_with_demo_label(self):
        with patch.object(demo, 'docker', side_effect=[json.dumps({
                'com.docker.compose.project': 'raa-p1-demo', 'com.docker.compose.service': 'postgres'}),
                json.dumps([{'Name': 'raa-g0-postgres-data'}])]):
            with self.assertRaisesRegex(RuntimeError, 'fresh-demo-volume-only'):
                demo.guard()

    def test_existing_database_is_preserved_without_mutation(self):
        with patch.object(demo, 'guard'), patch.object(demo, 'sql', return_value='1'), \
                patch.object(demo, 'docker') as command:
            with self.assertRaisesRegex(RuntimeError, 'fresh-business-database-required-no-reset'):
                demo.initialize()
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
