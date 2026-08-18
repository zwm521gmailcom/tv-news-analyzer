import asyncio
import json
import unittest
from unittest.mock import patch

from core.cookie_manager import CookieManager
from core.fetcher import TradingViewFetcher


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


class TradingViewFetcherTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_latest_uses_curl_transport(self):
        payload = {
            "items": [
                {
                    "id": "news-1",
                    "title": "Curl headline",
                    "published": 1777040000,
                    "urgency": 2,
                    "provider": {"id": "reuters", "name": "Reuters"},
                    "storyPath": "/news/example/",
                }
            ]
        }

        async def fake_get_session(self):  # pragma: no cover - must not be called
            raise AssertionError("fetch_latest should use curl transport, not aiohttp")

        captured_cmd = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            body = json.dumps(payload)
            stdout = f"{body}\n__TV_NEWS_STATUS__200\n".encode("utf-8")
            return _FakeProcess(stdout)

        cm = CookieManager()
        fetcher = TradingViewFetcher(cm)

        with patch.object(TradingViewFetcher, "_get_session", new=fake_get_session), patch(
            "core.fetcher.asyncio.create_subprocess_exec",
            new=fake_create_subprocess_exec,
        ):
            items = await fetcher.fetch_latest(lang="en")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Curl headline")
        self.assertEqual(items[0].provider, "Reuters")
        self.assertIn("curl", captured_cmd["cmd"][0])
        self.assertIn("news-flow/v2/news", " ".join(captured_cmd["cmd"]))


if __name__ == "__main__":
    unittest.main()
