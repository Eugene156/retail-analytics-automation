"""Private-file helper tests with HTTP mocks, not actual integration evidence."""
import hashlib
from html import escape
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from scripts import wp3_preview_local as helper

CID = UUID("00000000-0000-0000-0000-000000000033")


class LocalPreviewTests(unittest.TestCase):
    def test_redirect_refusal(self):
        self.assertIsNone(helper.NoRedirect().redirect_request(None, None, 302, "", {}, "http://other/"))

    def setup_root(self, temporary):
        root = Path(temporary)
        (root / ".local" / "wp2-api").mkdir(parents=True)
        token = "a" * 64
        (root / ".local" / "wp2-api" / "token").write_text(token, encoding="utf-8")
        payload = b'{"exact":0.73293010234875627641}'
        digest = hashlib.sha256(payload).hexdigest()
        metadata = json.dumps({"revision": 1, "approved": False, "published": False,
                               "payload_sha256": digest}).encode()
        page = (str(CID) + digest + escape(payload.decode(), quote=True)).encode()
        return root, token, metadata, payload, page

    def test_exclusive_file_repeat_and_changed_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, token, metadata, payload, page = self.setup_root(temporary)
            responses = [metadata, payload, page, metadata, payload]
            with patch.object(helper, "ROOT", root), patch.object(helper, "fetch", side_effect=responses * 2), patch("sys.stdout", new=io.StringIO()) as output:
                path = helper.save_preview(CID)
                self.assertEqual(helper.save_preview(CID), path)
                self.assertNotIn(token, output.getvalue())
            self.assertEqual(path.read_bytes(), page)
            changed = page + b" changed"
            with patch.object(helper, "ROOT", root), patch.object(helper, "fetch", side_effect=[metadata, payload, changed, metadata, payload]):
                with self.assertRaises(ValueError):
                    helper.save_preview(CID)
            self.assertEqual(path.read_bytes(), page)

    def test_token_tamper_and_read_changes_fail_before_file_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, token, metadata, payload, page = self.setup_root(temporary)
            for responses in ([metadata, payload, page + token.encode(), metadata, payload],
                              [metadata, payload, page, metadata + b" ", payload],
                              [metadata, payload, page, metadata, payload + b" "]):
                with patch.object(helper, "ROOT", root), patch.object(helper, "fetch", side_effect=responses):
                    with self.assertRaises(ValueError):
                        helper.save_preview(CID)
                self.assertFalse((root / "reports").exists())
            with patch.object(helper, "ROOT", root), patch.object(helper, "fetch", side_effect=[metadata, payload, page, metadata, payload]), \
                    patch.object(Path, "resolve", side_effect=[root.parent / "escaped.html", root]):
                with self.assertRaises(ValueError):
                    helper.save_preview(CID)
            self.assertFalse((root / "reports").exists())


if __name__ == "__main__":
    unittest.main()
