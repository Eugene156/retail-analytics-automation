"""Host-side helper/export/privacy tests; not actual n8n execution evidence."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wp3_n8n_local as local


class LocalHelperTests(unittest.TestCase):
    def test_sanitized_source_has_only_three_fixed_http_nodes(self):
        with patch.object(local, "secrets_to_protect", return_value=[]):
            source = local.source_workflow()
        nodes = [node for node in source["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"]
        self.assertEqual({node["name"] for node in nodes}, local.HTTP_NODES)
        self.assertFalse(source["active"])
        self.assertFalse(source["pinData"])
        self.assertTrue(all("credentials" not in node for node in source["nodes"]))
        self.assertTrue(all("http://raa-wp2-api:8000/api/v1/" in node["parameters"]["url"] for node in nodes))

    def test_cli_json_extraction_accepts_prefix_but_not_wrong_structure(self):
        expected = {"data": {"resultData": {"lastNodeExecuted": "Example"}}}
        output = "Startup [noise]\n{}\n" + json.dumps(expected)
        predicate = lambda value: isinstance(value, dict) and "data" in value
        self.assertEqual(local.extract_json(output, predicate), expected)
        with self.assertRaises(local.CheckFailure):
            local.extract_json("prefix {}", predicate)

    def test_command_output_cannot_expose_private_values(self):
        result = subprocess.CompletedProcess([], 0, stdout="private-test-value", stderr="")
        with patch.object(local.subprocess, "run", return_value=result), \
                patch.object(local, "secrets_to_protect", return_value=["private-test-value"]):
            with self.assertRaises(local.CheckFailure) as error:
                local.invoke(["exec", "unused"])
        self.assertEqual(str(error.exception), "captured-output-secret-check")
        self.assertNotIn("private-test-value", str(error.exception))

    def test_actual_export_shape_is_sanitized_and_matches_source(self):
        with patch.object(local, "secrets_to_protect", return_value=[]):
            source = local.source_workflow()
        exported = deepcopy(source)
        for node in exported["nodes"]:
            if node["name"] in local.HTTP_NODES:
                node["credentials"] = {"httpHeaderAuth": {"id": "local-reference", "name": "Local"}}
        exported["versionId"] = "test-version"
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps([exported]), stderr="")
        with redirect_stdout(StringIO()), patch.object(local, "guard"), patch.object(local, "invoke", return_value=result), \
                patch.object(local, "secrets_to_protect", return_value=[]):
            local.export_check()
            exported["nodes"][0]["parameters"] = {"unexpected": True}
            result.stdout = json.dumps([exported])
            with self.assertRaises(local.CheckFailure) as error:
                local.export_check()
            self.assertEqual(str(error.exception), "live-export-source-roundtrip")

    def test_cli_cannot_stop_main_with_active_workflows(self):
        with patch.object(local, "sql", return_value="1"), patch.object(local, "invoke") as invoke:
            with self.assertRaises(local.CheckFailure) as error:
                local.execute_workflow()
            self.assertEqual(str(error.exception), "no-active-workflow-before-cli")
            invoke.assert_not_called()
        with self.assertRaises(local.CheckFailure):
            local.execute_workflow("unscoped-workflow")


if __name__ == "__main__":
    unittest.main()
