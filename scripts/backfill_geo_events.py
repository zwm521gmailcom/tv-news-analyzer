"""
地理位置回填脚本 — 对数据库中已有新闻批量提取地理位置。

用法:
    python3 scripts/backfill_geo_events.py --limit 5000 --delay 0.1

注意: 使用同步 sqlite3 以避免数据库锁问题。
"""

import argparse
import json
import sqlite3
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings
from core.geo_extractor import extract_geo


def get_db():
    db = sqlite3.connect(settings.DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def save_geo_event(db, geo):
    db.execute(
        """INSERT OR REPLACE INTO geo_events
           (id, news_id, latitude, longitude, location_name, country_code,
            region, geom_source, urgency, published, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (geo.id, geo.news_id, geo.latitude, geo.longitude,
         geo.location_name, geo.country_code, geo.region,
         geo.geom_source, geo.urgency, geo.published, geo.created_at)
    )


def backfill_geo_events(limit: int = 5000, delay: float = 0.1):
    """
    对尚未提取地理位置的新闻批量处理。
    """
    # 首先运行 DDL 创建新表（如果不存在）
    print("[Backfill] 初始化数据库表...")
    init_db = sqlite3.connect(settings.DB_PATH)
    init_db.executescript("""
CREATE TABLE IF NOT EXISTS geo_events (
    id              TEXT PRIMARY KEY,
    news_id         TEXT NOT NULL,
    latitude        REAL,
    longitude       REAL,
    location_name   TEXT,
    country_code    TEXT,
    region          TEXT,
    geom_source     TEXT,
    urgency         INTEGER,
    published       INTEGER,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (news_id) REFERENCES raw_news(id)
);
CREATE INDEX IF NOT EXISTS idx_geo_events_published ON geo_events(published DESC);
CREATE INDEX IF NOT EXISTS idx_geo_events_country   ON geo_events(country_code);
CREATE INDEX IF NOT EXISTS idx_geo_events_region     ON geo_events(region);

CREATE TABLE IF NOT EXISTS event_summaries (
    id              TEXT PRIMARY KEY,
    hour_bucket     INTEGER NOT NULL UNIQUE,
    top_events      TEXT,
    ai_narrative    TEXT,
    event_count     INTEGER NOT NULL DEFAULT 0,
    flash_count     INTEGER NOT NULL DEFAULT 0,
    computed_at     INTEGER NOT NULL,
    computed_by     TEXT NOT NULL DEFAULT 'ollama'
);
CREATE INDEX IF NOT EXISTS idx_event_summaries_hour ON event_summaries(hour_bucket DESC);

CREATE TABLE IF NOT EXISTS event_relations (
    id              TEXT PRIMARY KEY,
    from_news_id    TEXT NOT NULL,
    to_news_id      TEXT NOT NULL,
    relation_type   TEXT NOT NULL,
    confidence      REAL,
    ai_explanation  TEXT,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (from_news_id) REFERENCES raw_news(id),
    FOREIGN KEY (to_news_id)   REFERENCES raw_news(id)
);
CREATE INDEX IF NOT EXISTS idx_event_relations_from ON event_relations(from_news_id);
CREATE INDEX IF NOT EXISTS idx_event_relations_to   ON event_relations(to_news_id);
CREATE INDEX IF NOT EXISTS idx_event_relations_type ON event_relations(relation_type);
    """)
    init_db.close()

    db = get_db()
    # 已有地理位置的新闻 ID
    cur_existing = db.execute("SELECT news_id FROM geo_events")
    existing_ids = {row[0] for row in cur_existing.fetchall()}
    print(f"[Backfill] 已有 {len(existing_ids)} 条新闻提取过地理位置")

    # 取出没有地理位置的新闻
    cur = db.execute(
        """SELECT id, title, short_desc, story_body, urgency, provider,
                  published, symbols, is_flash, lang, market, fetched_at, raw_json
           FROM raw_news
           ORDER BY published DESC
           LIMIT ?""",
        (limit,)
    )
    rows = cur.fetchall()
    print(f"[Backfill] 待处理 {len(rows)} 条新闻（上限 {limit}）")

    processed = 0
    geo_count = 0
    start_time = time.time()

    for r in rows:
        news_id = r["id"]
        if news_id in existing_ids:
            continue

        from db.models import RawNews
        news = RawNews(
            id=news_id,
            title=r["title"],
            short_desc=r["short_desc"],
            story_body=r["story_body"],
            urgency=r["urgency"],
            provider=r["provider"],
            published=r["published"],
            symbols=json.loads(r["symbols"] or "[]"),
            is_flash=bool(r["is_flash"]),
            lang=r["lang"],
            market=r["market"],
            fetched_at=r["fetched_at"],
            raw_json=r["raw_json"],
        )

        geo = extract_geo(news)
        if geo:
            save_geo_event(db, geo)
            geo_count += 1
            processed += 1
            if processed % 100 == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"[Backfill] 进度: {processed}/{len(rows)} — 命中率: {geo_count} — {rate:.1f} 条/秒")
                db.commit()
        else:
            processed += 1

        if delay > 0:
            time.sleep(delay)

    db.commit()
    elapsed = time.time() - start_time
    print(f"[Backfill] 完成! 共处理 {processed} 条，新增地理位置 {geo_count} 条，耗时 {elapsed:.1f} 秒")
    if processed > 0:
        print(f"[Backfill] 命中率: {geo_count / processed * 100:.1f}%")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="地理位置回填")
    parser.add_argument("--limit", type=int, default=5000, help="最多处理多少条新闻（默认 5000）")
    parser.add_argument("--delay", type=float, default=0.05, help="每条新闻间隔秒数（默认 0.05）")
    args = parser.parse_args()

    print(f"[Backfill] 开始回填... limit={args.limit} delay={args.delay}")
    backfill_geo_events(limit=args.limit, delay=args.delay)
