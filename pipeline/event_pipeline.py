"""
事件分析 Pipeline — 地理位置提取 + 小时摘要 + 事件关联。

由 Scheduler 每小时末触发，或由脚本手动运行。
"""

import asyncio
import json
import time
from collections import Counter

from db.database import get_db
from db.models import RawNews, GeoEvent, EventSummary, EventRelation
from db.repository import NewsRepository
from core.geo_extractor import extract_geo


async def process_hourly_events(hour_bucket: int, lookback_hours: int = 6):
    """
    处理指定小时桶的事件分析。

    流程:
      1. 读取该小时 + 之前 N 小时的新闻
      2. geo_extractor 提取地理位置（只处理新增的）
      3. 计算小时摘要
      4. 计算事件关联
      5. 全部写入 DB
    """
    since = hour_bucket - lookback_hours * 3600

    async with get_db() as db:
        repo = NewsRepository(db)

        # ── Step 1: 读取新闻 ────────────────────────────────
        # 转换为小时范围
        cur = await db.execute(
            """SELECT id, title, short_desc, story_body, urgency, provider,
                      published, symbols, is_flash, lang, market, fetched_at, raw_json
               FROM raw_news
               WHERE published >= ? AND published < ?
               ORDER BY published DESC""",
            (hour_bucket, hour_bucket + 3600)
        )
        rows = await cur.fetchall()
        news_list = []
        for r in rows:
            news_list.append(RawNews(
                id=r["id"], title=r["title"], short_desc=r["short_desc"],
                story_body=r["story_body"], urgency=r["urgency"],
                provider=r["provider"], published=r["published"],
                symbols=json.loads(r["symbols"] or "[]"),
                is_flash=bool(r["is_flash"]), lang=r["lang"],
                market=r["market"], fetched_at=r["fetched_at"],
                raw_json=r["raw_json"],
            ))

        print(f"[EventPipeline] {time.strftime('%Y-%m-%d %H:00', time.localtime(hour_bucket))} — {len(news_list)} 条新闻")

        if not news_list:
            return

        # ── Step 2: 提取地理位置 ───────────────────────────
        existing_ids = await repo.get_geo_news_ids_since(since)
        geo_count = 0
        for n in news_list:
            if n.id not in existing_ids:
                geo = extract_geo(n)
                if geo:
                    await repo.save_geo_event(geo)
                    geo_count += 1
        print(f"[EventPipeline] 地理位置提取: {geo_count} 条新标注")

        # ── Step 3: 计算小时摘要 ────────────────────────────
        summary = _compute_hourly_summary(hour_bucket, news_list)
        if summary:
            await repo.save_event_summary(summary)
            print(f"[EventPipeline] 小时摘要: {summary.event_count} 条事件, AI叙事: {summary.ai_narrative[:50] if summary.ai_narrative else 'N/A'}...")

        # ── Step 4: 计算事件关联 ───────────────────────────
        # 读所有相关新闻（用于关联计算）
        all_cur = await db.execute(
            """SELECT id, title, short_desc, urgency, provider,
                      published, symbols, is_flash, lang, market
               FROM raw_news WHERE published >= ? ORDER BY published DESC LIMIT 200""",
            (since,)
        )
        all_rows = await all_cur.fetchall()
        all_news = [
            {
                "id": r["id"], "title": r["title"], "short_desc": r["short_desc"],
                "urgency": r["urgency"], "provider": r["provider"],
                "published": r["published"],
                "symbols": json.loads(r["symbols"] or "[]"),
                "is_flash": bool(r["is_flash"]), "lang": r["lang"], "market": r["market"],
            }
            for r in all_rows
        ]

        relations = _compute_event_relations(all_news)
        if relations:
            await repo.save_event_relations(relations)
            print(f"[EventPipeline] 事件关联: {len(relations)} 条")


def _compute_hourly_summary(hour_bucket: int, news_list: list) -> EventSummary:
    """
    生成小时事件摘要。
    策略:
      - 按 urgency + is_flash 降序取前 3 条
      - 找共享 symbol 最多的作为叙事中心
      - 生成一句话叙事
    """
    if not news_list:
        return None

    sorted_news = sorted(
        news_list,
        key=lambda x: (x.urgency or 0, bool(x.is_flash)),
        reverse=True,
    )
    top = sorted_news[:3]

    # 统计共享 symbol
    all_symbols = []
    for n in news_list:
        all_symbols.extend(n.symbols or [])
    sym_counter = Counter(all_symbols)
    top_symbol = sym_counter.most_common(1)
    top_symbol_name = top_symbol[0][0] if top_symbol else ""

    top_events = [
        {
            "news_id":  n.id,
            "title":    n.title,
            "urgency":  n.urgency,
            "summary":  n.short_desc or "",
            "symbols":  (n.symbols or [])[:3],
        }
        for n in top
    ]

    # 生成叙事
    if top_symbol_name:
        sym_display = top_symbol_name.split(":")[-1] if ":" in top_symbol_name else top_symbol_name
        narrative = f"本小时共 {len(news_list)} 条事件，{sym_display} 相关新闻最密集"
        if top[0].short_desc:
            narrative += f"；重点：{top[0].title[:40]}"
    else:
        narrative = f"本小时共 {len(news_list)} 条事件"
        if top[0].title:
            narrative += f"；重点：{top[0].title[:40]}"

    return EventSummary(
        id=f"es_{hour_bucket}",
        hour_bucket=hour_bucket,
        top_events=top_events,
        ai_narrative=narrative,
        event_count=len(news_list),
        flash_count=sum(1 for n in news_list if n.is_flash),
        computed_at=int(time.time()),
        computed_by="keyword_fallback",
    )


def _compute_event_relations(news_list: list[dict], max_relations: int = 300) -> list[EventRelation]:
    """
    基于 symbol 共享 + 时间邻近计算事件关联。
    返回去重后的关联列表。
    """
    relations = []

    # ── Symbol 共享关联 ───────────────────────────────────
    sym_map: dict[str, set[str]] = {}
    for n in news_list:
        for s in n.get("symbols", []):
            sym_map.setdefault(s, set()).add(n["id"])

    for sym, news_ids in sym_map.items():
        id_list = list(news_ids)
        for i in range(len(id_list)):
            for j in range(i + 1, len(id_list)):
                rel_id = f"rel_s_{id_list[i][:16]}_{id_list[j][:16]}"
                relations.append(EventRelation(
                    id=rel_id,
                    from_news_id=id_list[i],
                    to_news_id=id_list[j],
                    relation_type="symbol_shared",
                    confidence=0.7,
                    ai_explanation=f"Both events mention {sym.split(':')[-1]}",
                    created_at=int(time.time()),
                ))

    # ── 时间邻近关联 ─────────────────────────────────────
    hour_groups: dict[int, list[dict]] = {}
    for n in news_list:
        h = (n["published"] // 3600) * 3600
        hour_groups.setdefault(h, []).append(n)

    for hour, items in hour_groups.items():
        if len(items) >= 2:
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    rel_id = f"rel_t_{items[i]['id'][:16]}_{items[j]['id'][:16]}"
                    from_ts = time.localtime(items[i]["published"])
                    to_ts = time.localtime(items[j]["published"])
                    relations.append(EventRelation(
                        id=rel_id,
                        from_news_id=items[i]["id"],
                        to_news_id=items[j]["id"],
                        relation_type="time_proximate",
                        confidence=0.4,
                        ai_explanation=f"Same hour ({time.strftime('%H:00', from_ts)})",
                        created_at=int(time.time()),
                    ))

    # ── 去重：同 from/to 只保留最高 confidence ─────────────
    best: dict[tuple[str, str], EventRelation] = {}
    for rel in relations:
        key = (rel.from_news_id, rel.to_news_id)
        if key not in best or rel.confidence > best[key].confidence:
            best[key] = rel

    return list(best.values())[:max_relations]


async def run_current_hour():
    """处理当前小时（由 Scheduler 每小时末调用）"""
    current_hour = (int(time.time()) // 3600) * 3600
    await process_hourly_events(current_hour)


async def run_historical(hours: int = 48):
    """回填历史 N 小时的事件分析"""
    current_hour = (int(time.time()) // 3600) * 3600
    for h in range(current_hour, current_hour - hours * 3600, -3600):
        await process_hourly_events(h)


if __name__ == "__main__":
    print("[EventPipeline] 开始运行...")
    asyncio.run(run_historical(hours=24))
    print("[EventPipeline] 完成")
