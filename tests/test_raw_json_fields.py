import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import DDL
from core.raw_json_fields import (
    extract_sector_country_from_related_symbols,
    infer_corp_activity_from_text,
)
from scripts.backfill_raw_fields import backfill_raw_fields


class RawJsonFieldBackfillTest(unittest.TestCase):
    def test_extract_sector_and_country_from_any_logoid_keys(self):
        related_symbols = [
            {"symbol": "FX:AUDUSD", "currency-logoid": "country/US", "base-currency-logoid": "country/AU"},
            {"symbol": "NYSE:ENPH", "logoid": "sector/energy"},
        ]

        sector, country = extract_sector_country_from_related_symbols(related_symbols)

        self.assertEqual(sector, "energy")
        self.assertEqual(country, "US")

    def test_infer_corp_activity_from_text(self):
        activity = infer_corp_activity_from_text(
            "Company declares quarterly dividend and raises payout",
            "",
            "",
        )

        self.assertEqual(activity, "dividends")

    def test_backfill_raw_fields_overwrites_sector_country_and_corp_activity(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            conn = sqlite3.connect(db_path)
            conn.executescript(DDL)
            conn.execute("ALTER TABLE raw_news ADD COLUMN sector TEXT")
            conn.execute("ALTER TABLE raw_news ADD COLUMN country TEXT")
            conn.execute("ALTER TABLE raw_news ADD COLUMN corp_activity TEXT")
            conn.execute(
                """
                INSERT INTO raw_news (
                    id, title, short_desc, urgency, provider, published,
                    symbols, story_body, is_flash, lang, market, sector,
                    corp_activity, country, fetched_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "news-1",
                    "Company declares quarterly dividend and raises payout",
                    None,
                    2,
                    "sample-provider",
                    1,
                    "[]",
                    None,
                    0,
                    "en",
                    "unknown",
                    "old-sector",
                    "old-activity",
                    "old-country",
                    1,
                    json.dumps(
                        {
                            "id": "news-1",
                            "title": "Company declares quarterly dividend and raises payout",
                            "urgency": 2,
                            "provider": {"name": "sample-provider"},
                            "published": 1,
                            "is_flash": False,
                            "relatedSymbols": [
                                {"symbol": "FX:AUDUSD", "currency-logoid": "country/US", "base-currency-logoid": "country/AU"},
                                {"symbol": "NYSE:ENPH", "logoid": "sector/energy"},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
            conn.close()

            updated = backfill_raw_fields(db_path, limit=10, overwrite=True)
            self.assertEqual(updated, 1)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT market, sector, corp_activity, country FROM raw_news WHERE id = ?",
                ("news-1",),
            ).fetchone()
            self.assertEqual(row["market"], "forex")
            self.assertEqual(row["sector"], "energy")
            self.assertEqual(row["corp_activity"], "dividends")
            self.assertEqual(row["country"], "US")
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
