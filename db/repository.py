import json
import time
import aiosqlite
from typing import Optional
from db.models import RawNews, GeoEvent, EventSummary, EventRelation


class NewsRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    # ── 原始新闻 ─────────────────────────────────────────────

    async def save_news_batch(self, news_list: list[RawNews]) -> int:
        """批量写入，INSERT OR IGNORE 防重复，返回实际新增数量"""
        inserted = 0
        for n in news_list:
            cur = await self.db.execute(
                """INSERT OR IGNORE INTO raw_news
                   (id, title, short_desc, urgency, provider, published,
                    symbols, story_body, is_flash, lang, market,
                    sector, corp_activity, country,
                    fetched_at, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (n.id, n.title, n.short_desc, n.urgency, n.provider,
                 n.published, json.dumps(n.symbols), n.story_body,
                 int(n.is_flash), n.lang, n.market,
                 n.sector, n.corp_activity, n.country,
                 n.fetched_at, n.raw_json)
            )
            if cur.rowcount:
                inserted += 1
        await self.db.commit()
        return inserted

    async def save_story_body(self, news_id: str, body: str) -> None:
        """回写正文内容"""
        await self.db.execute(
            "UPDATE raw_news SET story_body = ? WHERE id = ?",
            (body, news_id)
        )
        await self.db.commit()

    async def get_news_without_body(self, limit: int = 200) -> list[tuple[str, str]]:
        """返回 story_body 为空的 (id, lang) 列表，按发布时间倒序"""
        cur = await self.db.execute(
            """SELECT id, lang FROM raw_news
               WHERE story_body IS NULL OR length(story_body) < 5
               ORDER BY published DESC LIMIT ?""",
            (limit,)
        )
        return [(row[0], row[1]) for row in await cur.fetchall()]

    async def exists(self, news_id: str) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM raw_news WHERE id=?", (news_id,)
        )
        return await cur.fetchone() is not None

    async def filter_new_ids(self, ids: list[str]) -> list[str]:
        """返回 ids 中尚未存入 DB 的部分"""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        cur = await self.db.execute(
            f"SELECT id FROM raw_news WHERE id IN ({placeholders})", ids
        )
        existing = {row[0] for row in await cur.fetchall()}
        return [i for i in ids if i not in existing]

    # ── 系统状态 ──────────────────────────────────────────────

    async def set_state(self, key: str, value: str):
        await self.db.execute(
            """INSERT INTO system_state (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
               updated_at=excluded.updated_at""",
            (key, value, int(time.time()))
        )
        await self.db.commit()

    async def get_state(self, key: str, default: str = "") -> str:
        cur = await self.db.execute(
            "SELECT value FROM system_state WHERE key=?", (key,)
        )
        row = await cur.fetchone()
        return row["value"] if row else default

    # ── 查询（CLI 用）────────────────────────────────────────

    async def query_raw_news(
        self,
        hours: int = 24,
        lang: Optional[str] = None,
        market: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 20
    ) -> tuple[list[dict], int]:
        """
        查询原始新闻。
        返回 (rows, total_count)，total_count 是不限 limit 的总匹配数。
        """
        since = int(time.time()) - hours * 3600
        conditions = ["published >= ?"]
        params: list = [since]
        if lang:
            conditions.append("lang=?")
            params.append(lang)
        if market:
            conditions.append("market=?")
            params.append(market)
        if symbol:
            conditions.append("symbols LIKE ?")
            params.append(f"%{symbol}%")
        where = " AND ".join(conditions)

        cnt_cur = await self.db.execute(
            f"SELECT COUNT(*) FROM raw_news WHERE {where}", params
        )
        total = (await cnt_cur.fetchone())[0]

        cur = await self.db.execute(
            f"""SELECT id, title, short_desc,
                       lang, market, urgency, provider, published,
                       symbols, is_flash
                FROM raw_news
                WHERE {where}
                ORDER BY published DESC
                LIMIT ?""",
            params + [limit]
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── 地理位置 ──────────────────────────────────────────────

    async def save_geo_event(self, geo: GeoEvent) -> None:
        """保存地理位置事件（幂等）"""
        await self.db.execute(
            """INSERT OR REPLACE INTO geo_events
               (id, news_id, latitude, longitude, location_name, country_code,
                region, geom_source, urgency, published, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (geo.id, geo.news_id, geo.latitude, geo.longitude,
             geo.location_name, geo.country_code, geo.region,
             geo.geom_source, geo.urgency, geo.published, geo.created_at)
        )
        await self.db.commit()

    async def get_geo_news_ids_since(self, since: int) -> set[str]:
        """返回已提取过地理位置的新闻 ID"""
        cur = await self.db.execute(
            "SELECT news_id FROM geo_events WHERE published >= ?", (since,)
        )
        return {row[0] for row in await cur.fetchall()}

    async def get_geo_events(self, hours: int = 24, urgency_min: int = 0) -> list[dict]:
        """返回地图渲染所需的地理位置事件数据"""
        since = int(time.time()) - hours * 3600
        cur = await self.db.execute(
            """SELECT g.latitude, g.longitude, g.location_name, g.country_code,
                      g.region, g.urgency, g.geom_source,
                      r.id, r.title, r.short_desc, r.provider, r.published,
                      r.symbols, r.is_flash, r.lang, r.market
               FROM geo_events g
               JOIN raw_news r ON g.news_id = r.id
               WHERE g.published >= ? AND g.urgency >= ?
               ORDER BY g.published DESC""",
            (since, urgency_min)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── 事件摘要 ──────────────────────────────────────────────

    async def save_event_summary(self, summary: EventSummary) -> None:
        """保存小时事件摘要（幂等）"""
        await self.db.execute(
            """INSERT OR REPLACE INTO event_summaries
               (id, hour_bucket, top_events, ai_narrative, event_count,
                flash_count, computed_at, computed_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (summary.id, summary.hour_bucket, json.dumps(summary.top_events),
             summary.ai_narrative, summary.event_count, summary.flash_count,
             summary.computed_at, summary.computed_by)
        )
        await self.db.commit()

    async def get_event_summaries(self, hours: int = 24) -> list[dict]:
        """返回最近 N 小时的事件摘要"""
        since = int(time.time()) - hours * 3600
        cur = await self.db.execute(
            """SELECT id, hour_bucket, top_events, ai_narrative,
                      event_count, flash_count, computed_at, computed_by
               FROM event_summaries
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC""",
            (since,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_event_summary_by_hour(self, hour_bucket: int) -> Optional[dict]:
        """返回指定小时桶的摘要"""
        cur = await self.db.execute(
            "SELECT * FROM event_summaries WHERE hour_bucket = ?", (hour_bucket,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # ── 事件关联 ──────────────────────────────────────────────

    async def save_event_relations(self, relations: list[EventRelation]) -> None:
        """批量保存事件关联（幂等）"""
        for rel in relations:
            await self.db.execute(
                """INSERT OR REPLACE INTO event_relations
                   (id, from_news_id, to_news_id, relation_type, confidence,
                    ai_explanation, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (rel.id, rel.from_news_id, rel.to_news_id, rel.relation_type,
                 rel.confidence, rel.ai_explanation, rel.created_at)
            )
        await self.db.commit()

    async def get_event_relations(self, hours: int = 24, limit: int = 500) -> list[dict]:
        """返回最近 N 小时的事件关联"""
        since = int(time.time()) - hours * 3600
        # 找出该时段内的所有新闻
        cur = await self.db.execute(
            "SELECT id FROM raw_news WHERE published >= ?", (since,)
        )
        news_ids = [row[0] for row in await cur.fetchall()]
        if not news_ids:
            return []
        placeholders = ",".join("?" * len(news_ids))
        cur = await self.db.execute(
            f"""SELECT from_news_id, to_news_id, relation_type,
                       confidence, ai_explanation
                FROM event_relations
                WHERE from_news_id IN ({placeholders})
                   OR to_news_id IN ({placeholders})
                ORDER BY confidence DESC
                LIMIT ?""",
            news_ids + news_ids + [limit]
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_news_by_ids(self, news_ids: list[str]) -> list[dict]:
        """根据 ID 列表批量获取新闻"""
        if not news_ids:
            return []
        placeholders = ",".join("?" * len(news_ids))
        cur = await self.db.execute(
            f"""SELECT id, title, short_desc, urgency, provider, published,
                      symbols, is_flash, lang, market
               FROM raw_news
               WHERE id IN ({placeholders})""",
            news_ids
        )
        return [dict(r) for r in await cur.fetchall()]

    # ── 区域 AI 叙事 ─────────────────────────────────────────

    async def save_region_narrative(self, narrative: "RegionNarrative") -> None:
        """保存区域 AI 叙事（幂等）"""
        await self.db.execute(
            """INSERT OR REPLACE INTO region_narratives
               (id, hour_bucket, region, latitude, longitude, news_count,
                top_events, ai_brief, ai_reasoning, urgency_score,
                computed_at, computed_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (narrative.id, narrative.hour_bucket, narrative.region,
             narrative.latitude, narrative.longitude, narrative.news_count,
             json.dumps(narrative.top_events), narrative.ai_brief,
             narrative.ai_reasoning, narrative.urgency_score,
             narrative.computed_at, narrative.computed_by)
        )
        await self.db.commit()

    async def get_region_narratives(self, hours: int = 24) -> list[dict]:
        """返回最近 N 小时的区域 AI 叙事"""
        since = int(time.time()) - hours * 3600
        cur = await self.db.execute(
            """SELECT id, hour_bucket, region, latitude, longitude,
                      news_count, top_events, ai_brief, ai_reasoning,
                      urgency_score, computed_at, computed_by
               FROM region_narratives
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC, urgency_score DESC""",
            (since,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_geo_events_grouped_by_region(self, hours: int = 24) -> dict[str, list[dict]]:
        """按 region 分组返回地理位置事件"""
        since = int(time.time()) - hours * 3600
        cur = await self.db.execute(
            """SELECT g.region, g.latitude, g.longitude, g.location_name,
                      g.country_code, g.urgency, g.published,
                      r.id, r.title, r.short_desc, r.symbols, r.provider, r.market
               FROM geo_events g
               JOIN raw_news r ON g.news_id = r.id
               WHERE g.published >= ?
               ORDER BY g.urgency DESC""",
            (since,)
        )
        rows = await cur.fetchall()
        result = {}
        for r in rows:
            region = r["region"] or "Other"
            if region not in result:
                result[region] = []
            result[region].append(dict(r))
        return result

    # ── 小时因果链叙事 ────────────────────────────────────────

    async def save_hour_causal_narrative(self, narrative: "HourCausalNarrative") -> None:
        """保存小时因果链叙事（幂等）"""
        await self.db.execute(
            """INSERT OR REPLACE INTO hour_causal_narratives
               (id, hour_bucket, ai_chain, ai_summary, total_events,
                computed_at, computed_by)
               VALUES (?,?,?,?,?,?,?)""",
            (narrative.id, narrative.hour_bucket, json.dumps(narrative.ai_chain),
             narrative.ai_summary, narrative.total_events,
             narrative.computed_at, narrative.computed_by)
        )
        await self.db.commit()

    async def get_hour_causal_narratives(self, hours: int = 24) -> list[dict]:
        """返回最近 N 小时的小时因果链叙事"""
        since = int(time.time()) - hours * 3600
        cur = await self.db.execute(
            """SELECT id, hour_bucket, ai_chain, ai_summary,
                      total_events, computed_at, computed_by
               FROM hour_causal_narratives
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC""",
            (since,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_raw_news_for_hour(self, hour_bucket: int) -> list[dict]:
        """返回指定小时桶的所有原始新闻"""
        cur = await self.db.execute(
            """SELECT r.id, r.title, r.short_desc, r.urgency, r.provider,
                      r.published, r.symbols, r.is_flash, r.lang, r.market,
                      g.region, g.latitude, g.longitude
               FROM raw_news r
               LEFT JOIN geo_events g ON r.id = g.news_id
               WHERE r.published >= ? AND r.published < ?
               ORDER BY r.urgency DESC""",
            (hour_bucket, hour_bucket + 3600)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
