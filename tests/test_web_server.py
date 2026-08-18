import os
import sqlite3
import tempfile
import unittest
import asyncio
import json
import shutil

from db.database import init_db
import web.server as web_server


class WebServerDetailApiTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._old_db_path = web_server._settings.DB_PATH
        self._old_cookie_path = web_server._settings.COOKIE_PATH
        web_server._settings.DB_PATH = self.db_path

        self.cookie_dir = tempfile.mkdtemp(prefix="tvnews-cookies-")
        web_server._settings.COOKIE_PATH = os.path.join(self.cookie_dir, "cookies.json")
        with open(os.path.join(self.cookie_dir, "cookies.txt"), "w", encoding="utf-8") as f:
            f.write("")
        with open(web_server._settings.COOKIE_PATH, "w", encoding="utf-8") as f:
            json.dump({"cookies": {"sessionid": "cached-cookie"}}, f)

        asyncio.run(init_db())

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO raw_news (
                id, title, short_desc, urgency, provider, published,
                symbols, story_body, is_flash, lang, market, fetched_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "news-1",
                "Sample title",
                "Sample summary",
                2,
                "sample-provider",
                1777000000,
                "[]",
                "Sample body",
                0,
                "en",
                "unknown",
                1777000000,
                '{"link":"https://example.com/article","storyPath":"/news/news-1/"}',
            ),
        )
        conn.commit()
        conn.close()

        web_server.app.config["TESTING"] = True
        self.client = web_server.app.test_client()

    def tearDown(self):
        web_server._settings.DB_PATH = self._old_db_path
        web_server._settings.COOKIE_PATH = self._old_cookie_path
        shutil.rmtree(self.cookie_dir, ignore_errors=True)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_news_list_includes_short_desc(self):
        resp = self.client.get("/api/news?hours=24")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["short_desc"], "Sample summary")

    def test_news_detail_includes_short_desc(self):
        resp = self.client.get("/api/news_detail?id=news-1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["short_desc"], "Sample summary")
        self.assertEqual(data["link"], "https://example.com/article")
        self.assertEqual(data["story_path"], "/news/news-1/")

    def test_runtime_reports_anonymous_when_txt_is_blank(self):
        resp = self.client.get("/api/runtime")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["anonymous_mode"])
        self.assertEqual(data["cookie_source"], "paste_file_empty")
        self.assertEqual(data["cookie_count"], 0)


if __name__ == "__main__":
    unittest.main()
