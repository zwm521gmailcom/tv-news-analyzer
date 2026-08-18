import json
import os
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from core.cookie_manager import CookieManager


class CookieManagerLoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.cookie_json = os.path.join(self.tmp.name, "cookies.json")
        self.cookie_txt = os.path.join(self.tmp.name, "cookies.txt")

        patcher = patch.object(settings, "COOKIE_PATH", self.cookie_json)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_txt(self, content: str) -> None:
        with open(self.cookie_txt, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_json_cache(self, cookies: dict) -> None:
        with open(self.cookie_json, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookies, "saved_at": 123, "source": "file"}, f)

    def test_blank_txt_forces_anonymous_even_if_json_cache_exists(self):
        self._write_txt("   \n  ")
        self._write_json_cache({"sessionid": "cached"})

        cm = CookieManager()
        cm.load()

        self.assertEqual(cm.cookies, {})
        self.assertFalse(cm.is_authenticated)
        self.assertEqual(cm.source, "paste_file_empty")
        self.assertEqual(cm.get_headers(), {})

        with open(self.cookie_json, encoding="utf-8") as f:
            cached = json.load(f)
        self.assertEqual(cached["cookies"], {"sessionid": "cached"})

    def test_non_empty_txt_is_parsed_and_synced_to_json(self):
        self._write_txt("sessionid=abc123; tv_ecuid=xyz789")

        cm = CookieManager()
        cm.load()

        self.assertEqual(cm.cookies, {"sessionid": "abc123", "tv_ecuid": "xyz789"})
        self.assertTrue(cm.is_authenticated)
        self.assertEqual(cm.source, "paste_file")
        self.assertEqual(cm.get_headers(), {"Cookie": "sessionid=abc123; tv_ecuid=xyz789"})

        with open(self.cookie_json, encoding="utf-8") as f:
            cached = json.load(f)
        self.assertEqual(cached["cookies"], {"sessionid": "abc123", "tv_ecuid": "xyz789"})
        self.assertEqual(cached["source"], "paste_file")

    def test_missing_txt_falls_back_to_json_cache(self):
        self._write_json_cache({"sessionid": "cached"})

        cm = CookieManager()
        cm.load()

        self.assertEqual(cm.cookies, {"sessionid": "cached"})
        self.assertTrue(cm.is_authenticated)
        self.assertEqual(cm.source, "file")
        self.assertEqual(cm.get_headers(), {"Cookie": "sessionid=cached"})


if __name__ == "__main__":
    unittest.main()
