import aiosqlite
import os
from contextlib import asynccontextmanager
from config import settings


DDL = """
CREATE TABLE IF NOT EXISTS raw_news (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    short_desc      TEXT,
    urgency         INTEGER,
    provider        TEXT,
    published       INTEGER NOT NULL,
    symbols         TEXT,
    story_body      TEXT,
    is_flash        INTEGER NOT NULL DEFAULT 0,
    lang            TEXT NOT NULL DEFAULT 'en',
    market          TEXT NOT NULL DEFAULT 'unknown',
    fetched_at      INTEGER NOT NULL,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_news_published ON raw_news(published DESC);
CREATE INDEX IF NOT EXISTS idx_raw_news_urgency   ON raw_news(urgency);

CREATE TABLE IF NOT EXISTS system_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);

-- ── 地理位置事件表 ─────────────────────────────────────────
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

-- ── 小时事件摘要表 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS event_summaries (
    id              TEXT PRIMARY KEY,
    hour_bucket     INTEGER NOT NULL,
    top_events      TEXT,
    ai_narrative    TEXT,
    event_count     INTEGER NOT NULL DEFAULT 0,
    flash_count     INTEGER NOT NULL DEFAULT 0,
    computed_at     INTEGER NOT NULL,
    computed_by     TEXT NOT NULL DEFAULT 'ollama',
    UNIQUE(hour_bucket)
);
CREATE INDEX IF NOT EXISTS idx_event_summaries_hour ON event_summaries(hour_bucket DESC);

-- ── 事件关联表 ─────────────────────────────────────────────
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

-- ── 区域 AI 叙事表 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS region_narratives (
    id              TEXT PRIMARY KEY,
    hour_bucket     INTEGER NOT NULL,
    region          TEXT NOT NULL,
    latitude        REAL,
    longitude       REAL,
    news_count      INTEGER NOT NULL DEFAULT 0,
    top_events      TEXT,
    ai_brief        TEXT,
    ai_reasoning    TEXT,
    urgency_score   REAL,
    computed_at     INTEGER NOT NULL,
    computed_by     TEXT NOT NULL DEFAULT 'ollama',
    UNIQUE(hour_bucket, region)
);
CREATE INDEX IF NOT EXISTS idx_region_narratives_hour ON region_narratives(hour_bucket DESC);
CREATE INDEX IF NOT EXISTS idx_region_narratives_region ON region_narratives(region);

-- ── 小时因果链叙事表 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS hour_causal_narratives (
    id              TEXT PRIMARY KEY,
    hour_bucket     INTEGER NOT NULL UNIQUE,
    ai_chain        TEXT,
    ai_summary      TEXT,
    total_events    INTEGER,
    computed_at     INTEGER NOT NULL,
    computed_by     TEXT NOT NULL DEFAULT 'ollama'
);
CREATE INDEX IF NOT EXISTS idx_hour_causal_hour ON hour_causal_narratives(hour_bucket DESC);

-- ── 全局叙事表（跨时间/跨区域的全局关联分析）────────────────
CREATE TABLE IF NOT EXISTS global_narratives (
    id                  TEXT PRIMARY KEY,
    generated_at         INTEGER NOT NULL,
    lookback_hours       INTEGER NOT NULL,
    news_count           INTEGER,
    global_view          TEXT,
    insights             TEXT,
    symbol_network       TEXT,
    cross_region_links   TEXT,
    time_patterns        TEXT,
    computed_by          TEXT NOT NULL DEFAULT 'ollama',
    references_history_ids TEXT  -- v3: JSON 数组，记录本次参考了哪些历史 global_narrative
);
CREATE INDEX IF NOT EXISTS idx_global_generated ON global_narratives(generated_at DESC);

-- ── 多周期洞察表（每日/3日/每周/每月 + 板块预测）─────────────
CREATE TABLE IF NOT EXISTS period_insights (
    period              TEXT NOT NULL,                    -- 'daily' | '3day' | 'weekly' | 'monthly'
    period_start        INTEGER NOT NULL,                  -- unix ts
    period_end          INTEGER NOT NULL,
    news_count          INTEGER NOT NULL,
    market_breakdown    TEXT,                              -- JSON: {market: count}
    provider_breakdown  TEXT,                              -- JSON: top 10
    symbol_top          TEXT,                              -- JSON: top 10
    urgency_avg         REAL,
    ai_summary          TEXT,                              -- AI 摘要
    ai_themes           TEXT,                              -- JSON array of {title, detail}
    bullish_sectors     TEXT,                              -- JSON: [{sector, confidence, reason}]
    bearish_sectors     TEXT,                              -- JSON
    agent_score         REAL,
    generated_at        INTEGER NOT NULL,
    computed_by         TEXT NOT NULL DEFAULT 'minimax',
    PRIMARY KEY (period, period_start)
);
CREATE INDEX IF NOT EXISTS idx_period_lookup ON period_insights(period, period_start DESC);
CREATE TABLE IF NOT EXISTS period_insights_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    period              TEXT NOT NULL,                    -- 'daily' | '3day' | 'weekly' | 'monthly'
    period_start        INTEGER NOT NULL,
    period_end          INTEGER NOT NULL,
    news_count          INTEGER,
    market_breakdown    TEXT,                              -- JSON
    provider_breakdown  TEXT,
    symbol_top          TEXT,
    urgency_avg         REAL,
    ai_summary          TEXT,
    ai_themes           TEXT,                              -- JSON: [{title, detail, status}]
    bullish_sectors     TEXT,
    bearish_sectors     TEXT,
    agent_score         REAL,
    generated_at        INTEGER NOT NULL,
    computed_by         TEXT,
    -- 连续性元数据（生成后由代码 diff 上一期自动填）
    references_prior_id INTEGER,                            -- 本次基于哪个 prior id 生成
    new_themes          TEXT,                              -- 本期新出现的主题
    continued_themes    TEXT,                              -- 从上期延续的主题
    resolved_themes     TEXT,                              -- 上期已"消退"的主题
    trend               TEXT                               -- 'up'/'down'/'stable'/'mixed'
);
CREATE INDEX IF NOT EXISTS idx_history_period_time ON period_insights_history(period, generated_at DESC);
"""


_MIGRATIONS = [
    ("short_desc",  "ALTER TABLE raw_news ADD COLUMN short_desc TEXT"),
    ("lang",        "ALTER TABLE raw_news ADD COLUMN lang TEXT NOT NULL DEFAULT 'en'"),
    ("market",      "ALTER TABLE raw_news ADD COLUMN market TEXT NOT NULL DEFAULT 'unknown'"),
    ("sector",      "ALTER TABLE raw_news ADD COLUMN sector TEXT"),
    ("corp_activity","ALTER TABLE raw_news ADD COLUMN corp_activity TEXT"),
    ("country",     "ALTER TABLE raw_news ADD COLUMN country TEXT"),
]


async def _run_migrations(db: aiosqlite.Connection):
    """对已存在的旧库追加新列（幂等）"""
    cur = await db.execute("PRAGMA table_info(raw_news)")
    existing = {row[1] async for row in cur}
    for col_name, sql in _MIGRATIONS:
        if col_name not in existing:
            await db.execute(sql)

    await db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_raw_news_lang   ON raw_news(lang);
        CREATE INDEX IF NOT EXISTS idx_raw_news_market ON raw_news(market);
    """)
    await db.commit()


async def init_db():
    """初始化数据库（建表 + 迁移）"""
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(DDL)
        await _run_migrations(db)
        await db.commit()


@asynccontextmanager
async def get_db():
    """异步上下文管理器，用于 `async with get_db() as db:`"""
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(DDL)
        await _run_migrations(db)
        await db.commit()
        yield db
