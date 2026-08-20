"""
TradingView News Dashboard — Web Server
启动: python3 web/server.py
访问: http://localhost:5888
"""
import json
import sqlite3
import time
import os
import sys
import gzip
import shutil
import threading
from datetime import datetime, timedelta
from collections import Counter
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings as _settings
from core.cookie_manager import inspect_cookie_runtime

app = Flask(
    __name__,
    static_folder=os.path.dirname(os.path.abspath(__file__)),
    static_url_path="/static",
)
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Backup 配置 ──
BACKUP_DIR = os.path.join(os.path.dirname(WEB_DIR), "backups")
BACKUP_PREFIX = "tv_news_"
BACKUP_HOUR_DEFAULT = 3  # 每天 03:00 跑

# 备份 schedule 状态（内存，重启后从默认值恢复；用户可在 UI 改）
# 注：备份永不自动删除。所有备份保留在 BACKUP_DIR，由用户在 /backup 页面手动管理。
_backup_schedule = {
    "enabled": True,
    "hour": BACKUP_HOUR_DEFAULT,
    "last_run": None,   # ISO datetime
    "next_run": None,   # ISO datetime
}


def get_db():
    db = sqlite3.connect(_settings.DB_PATH)
    db.row_factory = sqlite3.Row
    return db


# ── API: Stats ────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    hours = int(request.args.get("hours", 24))
    since = int(time.time()) - hours * 3600
    db = get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM raw_news WHERE published >= ?", (since,)
        ).fetchone()[0]
        lang_rows = db.execute(
            "SELECT lang, COUNT(*) as n FROM raw_news WHERE published >= ? GROUP BY lang", (since,)
        ).fetchall()
        market_rows = db.execute(
            "SELECT market, COUNT(*) as n FROM raw_news WHERE published >= ? GROUP BY market ORDER BY n DESC", (since,)
        ).fetchall()
        sector_rows = db.execute(
            "SELECT sector, COUNT(*) as n FROM raw_news WHERE published >= ? AND sector IS NOT NULL GROUP BY sector ORDER BY n DESC", (since,)
        ).fetchall()
        country_rows = db.execute(
            "SELECT country, COUNT(*) as n FROM raw_news WHERE published >= ? AND country IS NOT NULL GROUP BY country ORDER BY n DESC", (since,)
        ).fetchall()
        latest = db.execute(
            "SELECT published FROM raw_news ORDER BY published DESC LIMIT 1"
        ).fetchone()
        db_total = db.execute("SELECT COUNT(*) FROM raw_news").fetchone()[0]
    finally:
        db.close()

    return jsonify({
        "total":       total,
        "db_total":    db_total,
        "by_lang":     {r["lang"]: r["n"] for r in lang_rows},
        "by_market":   {r["market"]: r["n"] for r in market_rows},
        "by_sector":   {r["sector"]: r["n"] for r in sector_rows},
        "by_country":  {r["country"]: r["n"] for r in country_rows},
        "latest_ts":   latest["published"] if latest else 0,
    })


# ── API: News ─────────────────────────────────────────────

@app.route("/api/news")
def api_news():
    hours  = int(request.args.get("hours", 24))
    lang   = request.args.get("lang")
    market = request.args.get("market")
    q      = request.args.get("q", "").strip()
    limit  = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    since = int(time.time()) - hours * 3600
    conditions = ["published >= ?"]
    params: list = [since]
    if lang:
        conditions.append("lang = ?"); params.append(lang)
    if market:
        conditions.append("market = ?"); params.append(market)
    if q:
        conditions.append("title LIKE ?")
        params.append(f"%{q}%")

    where = " AND ".join(conditions)
    db = get_db()
    try:
        total = db.execute(f"SELECT COUNT(*) FROM raw_news WHERE {where}", params).fetchone()[0]
        rows  = db.execute(
            f"""SELECT id, title,
                       short_desc, lang, market, sector, corp_activity, country,
                       urgency, provider, published, symbols, is_flash
                FROM raw_news WHERE {where}
                ORDER BY published DESC LIMIT ? OFFSET ?""",
            params + [limit, offset]
        ).fetchall()
    finally:
        db.close()

    items = []
    for r in rows:
        syms = json.loads(r["symbols"] or "[]")[:4]
        items.append({
            "id": r["id"], "title": r["title"],
            "short_desc": r["short_desc"],
            "lang": r["lang"], "market": r["market"],
            "sector": r["sector"], "corp_activity": r["corp_activity"],
            "country": r["country"],
            "urgency": r["urgency"],
            "provider": r["provider"], "published": r["published"],
            "symbols": syms, "is_flash": bool(r["is_flash"]),
        })
    return jsonify({"total": total, "items": items, "offset": offset})


# ── API: News Detail ──────────────────────────────────────

@app.route("/api/news_detail")
def api_news_detail():
    news_id = request.args.get("id", "").strip()
    if not news_id:
        return jsonify({"error": "missing id"}), 400
    db = get_db()
    try:
        row = db.execute(
            """SELECT id, title, short_desc, story_body, raw_json,
                      lang, market, sector, corp_activity, country,
                      urgency, provider, published, symbols, is_flash
               FROM raw_news WHERE id = ?""",
            (news_id,)
        ).fetchone()
    finally:
        db.close()

    if not row:
        return jsonify({"error": "not found"}), 404

    raw_payload = {}
    try:
        raw_payload = json.loads(row["raw_json"] or "{}")
    except Exception:
        raw_payload = {}

    syms = json.loads(row["symbols"] or "[]")
    return jsonify({
        "id":           row["id"],
        "title":        row["title"],
        "short_desc":   row["short_desc"],
        "story_body":   row["story_body"],
        "link":         raw_payload.get("link") or "",
        "story_path":   raw_payload.get("storyPath") or "",
        "lang":         row["lang"],
        "market":       row["market"],
        "sector":       row["sector"],
        "corp_activity":row["corp_activity"],
        "country":      row["country"],
        "urgency":      row["urgency"],
        "provider":     row["provider"],
        "published":    row["published"],
        "symbols":      syms,
        "is_flash":     bool(row["is_flash"]),
    })


@app.route("/api/runtime")
def api_runtime():
    return jsonify(inspect_cookie_runtime())


# ── API: Geo News（地图数据）───────────────────────────────

@app.route("/api/geo_news")
def api_geo_news():
    hours = int(request.args.get("hours", 24))
    urgency_min = int(request.args.get("urgency_min", 0))
    since = int(time.time()) - hours * 3600
    db = get_db()
    try:
        rows = db.execute(
            """SELECT g.latitude, g.longitude, g.location_name, g.country_code,
                      g.region, g.urgency, g.geom_source,
                      r.id, r.title, r.provider, r.published,
                      r.symbols, r.is_flash, r.lang, r.market
               FROM geo_events g
               JOIN raw_news r ON g.news_id = r.id
               WHERE g.published >= ? AND g.urgency >= ?
               ORDER BY g.published DESC""",
            (since, urgency_min)
        ).fetchall()
    finally:
        db.close()

    items = []
    for r in rows:
        items.append({
            "lat":       r["latitude"],
            "lng":       r["longitude"],
            "location":  r["location_name"],
            "country":   r["country_code"],
            "region":    r["region"],
            "urgency":   r["urgency"],
            "source":    r["geom_source"],
            "id":        r["id"],
            "title":     r["title"],
            "provider":  r["provider"],
            "published": r["published"],
            "symbols":   json.loads(r["symbols"] or "[]")[:4],
            "is_flash":  bool(r["is_flash"]),
            "lang":      r["lang"],
            "market":    r["market"],
        })
    return jsonify({"total": len(items), "items": items})


# ── API: Hourly Events（每小时事件汇总）────────────────────

@app.route("/api/hourly_events")
def api_hourly_events():
    hours = int(request.args.get("hours", 24))
    since = int(time.time()) - hours * 3600
    current_hour = (int(time.time()) // 3600) * 3600

    db = get_db()
    try:
        # 已有摘要的小时桶
        summary_rows = db.execute(
            """SELECT id, hour_bucket, top_events, ai_narrative,
                      event_count, flash_count, computed_at, computed_by
               FROM event_summaries
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC""",
            (since,)
        ).fetchall()

        hours_with_summary = {r["hour_bucket"] for r in summary_rows}
        results = []

        # 遍历每个小时桶
        for h in range(current_hour, since - 3600, -3600):
            if h in hours_with_summary:
                row = next(r for r in summary_rows if r["hour_bucket"] == h)
                results.append({
                    "hour":        h,
                    "hour_label":  _hour_label(h),
                    "top_events":  json.loads(row["top_events"] or "[]"),
                    "narrative":   row["ai_narrative"],
                    "event_count":  row["event_count"],
                    "flash_count": row["flash_count"],
                    "computed_by": row["computed_by"],
                    "computed_at": row["computed_at"],
                })
            else:
                # 实时从 raw_news 聚合（仅当有新闻时）
                news_in_hour = db.execute(
                    """SELECT id, title, urgency, symbols, is_flash
                       FROM raw_news
                       WHERE published >= ? AND published < ?
                       ORDER BY urgency DESC LIMIT 5""",
                    (h, h + 3600)
                ).fetchall()
                total_in_hour = db.execute(
                    "SELECT COUNT(*) FROM raw_news WHERE published >= ? AND published < ?",
                    (h, h + 3600)
                ).fetchone()[0]
                flash_in_hour = db.execute(
                    "SELECT COUNT(*) FROM raw_news WHERE published >= ? AND published < ? AND is_flash=1",
                    (h, h + 3600)
                ).fetchone()[0]
                if total_in_hour > 0:
                    top_events = [
                        {
                            "news_id": n["id"],
                            "title":   n["title"],
                            "urgency": n["urgency"],
                            "symbols": json.loads(n["symbols"] or "[]")[:3],
                        }
                        for n in news_in_hour
                    ]
                    results.append({
                        "hour":        h,
                        "hour_label":  _hour_label(h),
                        "top_events":  top_events,
                        "narrative":   None,
                        "event_count": total_in_hour,
                        "flash_count": flash_in_hour,
                        "computed_by": "realtime",
                        "computed_at": int(time.time()),
                    })
        return jsonify({"hours": results})
    finally:
        db.close()


# ── API: Event Graph（事件关系图）──────────────────────────

@app.route("/api/event_graph")
def api_event_graph():
    hours = int(request.args.get("hours", 0))
    limit = int(request.args.get("limit", 3000))
    since = int(time.time()) - hours * 3600 if hours > 0 else 0

    db = get_db()
    try:
        if since > 0:
            news_rows = db.execute(
                """SELECT id, title, urgency, provider, published,
                          symbols, is_flash, lang, market,
                          sector, corp_activity, country
                 FROM raw_news WHERE published >= ?
                 ORDER BY published DESC LIMIT ?""",
                (since, limit)
            ).fetchall()
        else:
            news_rows = db.execute(
                """SELECT id, title, urgency, provider, published,
                          symbols, is_flash, lang, market,
                          sector, corp_activity, country
                 FROM raw_news
                 ORDER BY published DESC LIMIT ?""",
                (limit,)
            ).fetchall()

        # 构建新闻节点
        nodes = []
        news_map = {}  # id -> node
        for r in news_rows:
            node = {
                "id":        r["id"],
                "title":     r["title"],
                "urgency":   r["urgency"],
                "provider":  r["provider"],
                "published": r["published"],
                "time_label": _time_label(r["published"]),
                "symbols":   json.loads(r["symbols"] or "[]")[:3],
                "is_flash":  bool(r["is_flash"]),
                "lang":      r["lang"],
                "market":    r["market"] or "unknown",
                "sector":    r["sector"],
                "corp_activity": r["corp_activity"],
                "country":   r["country"],
                "nodeType":  "news",
            }
            nodes.append(node)
            news_map[r["id"]] = node

        # 新闻之间根据共同属性建立连接
        edges = []
        added_pairs = set()

        # 按属性分组新闻
        def group_by_attr(rows, attr):
            groups = {}
            for r in rows:
                val = r[attr] or "unknown"
                if val not in groups:
                    groups[val] = []
                groups[val].append(r["id"])
            return groups

        # 市场分组
        market_groups = group_by_attr(news_rows, "market")
        # 板块分组
        sector_groups = group_by_attr(news_rows, "sector")
        # 国家分组
        country_groups = group_by_attr(news_rows, "country")
        # 供应商分组
        provider_groups = group_by_attr(news_rows, "provider")
        # 符号分组（只取前3个符号）
        symbol_groups = {}
        for r in news_rows:
            syms = json.loads(r["symbols"] or "[]")[:3]
            for sym in syms:
                if sym not in symbol_groups:
                    symbol_groups[sym] = []
                symbol_groups[sym].append(r["id"])

        # 边的权重映射
        edge_weights = {
            "market": 0.3,
            "sector": 0.4,
            "country": 0.5,
            "provider": 0.6,
            "symbol": 0.8,
        }

        # 添加边（限制每个属性最多产生一定数量的边）
        def add_edges_from_group(group, attr_name, max_per_group=8):
            for val, news_ids in group.items():
                if len(news_ids) < 2:
                    continue
                count = 0
                for i in range(len(news_ids)):
                    for j in range(i + 1, len(news_ids)):
                        if count >= max_per_group:
                            break
                        pair = tuple(sorted([news_ids[i], news_ids[j]]))
                        if pair not in added_pairs:
                            added_pairs.add(pair)
                            edges.append({
                                "source": news_ids[i],
                                "target": news_ids[j],
                                "type": f"shared_{attr_name}",
                                "confidence": edge_weights.get(attr_name, 0.5),
                            })
                            count += 1

        add_edges_from_group(market_groups, "market", max_per_group=5)
        add_edges_from_group(sector_groups, "sector", max_per_group=8)
        add_edges_from_group(country_groups, "country", max_per_group=6)
        add_edges_from_group(provider_groups, "provider", max_per_group=4)
        add_edges_from_group(symbol_groups, "symbol", max_per_group=10)

        return jsonify({"nodes": nodes, "edges": edges})
    finally:
        db.close()


def _hour_label(h: int) -> str:
    """将 Unix 时间戳转换为 'HH:00' 格式（北京时间）"""
    import datetime
    return datetime.datetime.fromtimestamp(h, tz=_BJ_TZ).strftime("%H:00")


def _time_label(ts: int) -> str:
    """将 Unix 时间戳转换为 'HH:MM' 格式（北京时间）"""
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=_BJ_TZ).strftime("%H:%M")


import datetime as _dt
_BJ_TZ = _dt.timezone(_dt.timedelta(hours=8))


# ── API: Analytics ────────────────────────────────────────

@app.route("/api/analytics/period")
def api_analytics_period():
    """按周/月/日聚合新闻量 + 语言拆分
    query: type=week|month|day (default week), limit=8 (default 8)
    """
    ptype = request.args.get("type", "week")
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be int"}), 400
    if limit < 1 or limit > 10000:
        return jsonify({"error": "limit 1-10000"}), 400

    fmt = {"week": "%Y-W%W", "month": "%Y-%m", "day": "%m-%d"}.get(ptype)
    if not fmt:
        return jsonify({"error": "type must be week|month|day"}), 400

    db = get_db()
    try:
        rows = db.execute(
            f"""SELECT strftime('{fmt}', datetime(published,'unixepoch')) AS period,
                       COUNT(*) AS total,
                       SUM(CASE WHEN lang='en'      THEN 1 ELSE 0 END) AS en,
                       SUM(CASE WHEN lang='zh-Hans' THEN 1 ELSE 0 END) AS zh,
                       SUM(CASE WHEN is_flash=1    THEN 1 ELSE 0 END) AS flash
                FROM raw_news
                GROUP BY period
                HAVING period IS NOT NULL
                ORDER BY period DESC
                LIMIT ?""", (limit,)
        ).fetchall()
    finally:
        db.close()
    periods = [
        {
            "period": r["period"],
            "total":  r["total"],
            "en":     r["en"]  or 0,
            "zh":     r["zh"]  or 0,
            "flash":  r["flash"] or 0,
        }
        for r in rows
    ]
    periods.reverse()  # 升序展示
    return jsonify({
        "type":    ptype,
        "limit":   limit,
        "count":   len(periods),
        "periods": periods,
    })


@app.route("/api/analytics")
def api_analytics():
    hours = int(request.args.get("hours", 24))
    since = int(time.time()) - hours * 3600
    db = get_db()
    try:
        market_dist = db.execute(
            "SELECT market, COUNT(*) n FROM raw_news WHERE published>=? GROUP BY market ORDER BY n DESC", (since,)
        ).fetchall()
        urgency_dist = db.execute(
            "SELECT urgency, COUNT(*) n FROM raw_news WHERE published>=? GROUP BY urgency ORDER BY urgency", (since,)
        ).fetchall()
        top_sources = db.execute(
            "SELECT provider, COUNT(*) n FROM raw_news WHERE published>=? GROUP BY provider ORDER BY n DESC LIMIT 15", (since,)
        ).fetchall()
        symbols_rows = db.execute(
            "SELECT symbols FROM raw_news WHERE published>=? AND symbols!='[]'", (since,)
        ).fetchall()
        hour_rows = db.execute(
            """SELECT strftime('%H:00', datetime(published,'unixepoch','localtime')) as hour,
                      COUNT(*) n FROM raw_news WHERE published>=?
               GROUP BY hour ORDER BY hour""", (since,)
        ).fetchall()
        lang_dist = db.execute(
            "SELECT lang, COUNT(*) n FROM raw_news WHERE published>=? GROUP BY lang", (since,)
        ).fetchall()
        flash_count = db.execute(
            "SELECT COUNT(*) FROM raw_news WHERE published>=? AND is_flash=1", (since,)
        ).fetchone()[0]
        cross = db.execute(
            "SELECT market, lang, COUNT(*) n FROM raw_news WHERE published>=? GROUP BY market,lang", (since,)
        ).fetchall()
        day_rows = db.execute(
            """SELECT strftime('%m-%d', datetime(published,'unixepoch','localtime')) as day,
                      COUNT(*) n FROM raw_news WHERE published>=?
               GROUP BY day ORDER BY day""", (since,)
        ).fetchall()
    finally:
        db.close()

    sym_counter = Counter()
    for row in symbols_rows:
        for s in json.loads(row[0] or "[]"):
            sym_counter[s.split(":")[-1] if ":" in s else s] += 1

    cross_map = {}
    for r in cross:
        cross_map.setdefault(r["market"], {})[r["lang"]] = r["n"]

    return jsonify({
        "market_dist":  [{"market": r["market"], "n": r["n"]} for r in market_dist],
        "urgency_dist": [{"urgency": r["urgency"], "n": r["n"]} for r in urgency_dist],
        "top_sources":  [{"provider": r["provider"], "n": r["n"]} for r in top_sources],
        "top_symbols":  [{"symbol": s, "n": n} for s, n in sym_counter.most_common(20)],
        "hour_series":  [{"hour": r["hour"], "n": r["n"]} for r in hour_rows],
        "day_series":   [{"day": r["day"], "n": r["n"]} for r in day_rows],
        "lang_dist":    [{"lang": r["lang"], "n": r["n"]} for r in lang_dist],
        "market_lang":  cross_map,
        "flash_count":  flash_count,
    })


# ── API: Map Regions（地图区域聚合 + AI 叙事）───────────────

@app.route("/api/map_regions")
def api_map_regions():
    """返回按区域聚合的 AI 叙事（地图用）"""
    hours = int(request.args.get("hours", 24))
    since = int(time.time()) - hours * 3600

    db = get_db()
    try:
        # 尝试从 region_narratives 表读取
        rows = db.execute(
            """SELECT id, hour_bucket, region, latitude, longitude,
                      news_count, top_events, ai_brief, ai_reasoning,
                      urgency_score, computed_at, computed_by
               FROM region_narratives
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC, urgency_score DESC""",
            (since,)
        ).fetchall()

        if rows:
            items = []
            for r in rows:
                items.append({
                    "region":    r["region"],
                    "lat":       r["latitude"],
                    "lng":       r["longitude"],
                    "news_count": r["news_count"],
                    "ai_brief":  r["ai_brief"],
                    "urgency_score": r["urgency_score"],
                    "hour_bucket": r["hour_bucket"],
                    "hour_label": _hour_label(r["hour_bucket"]),
                    "top_events": json.loads(r["top_events"] or "[]"),
                    "computed_by": r["computed_by"],
                })
            return jsonify({"regions": items, "source": "ai"})

        # 降级：从 geo_events 实时聚合
        geo_rows = db.execute(
            """SELECT region, latitude, longitude, urgency,
                      COUNT(*) as cnt
               FROM geo_events g
               WHERE g.published >= ?
               GROUP BY region
               ORDER BY urgency DESC""",
            (since,)
        ).fetchall()

        regions = []
        for r in geo_rows:
            region = r["region"] or "Other"
            news_rows = db.execute(
                """SELECT g.news_id, r.title, r.urgency
                   FROM geo_events g
                   JOIN raw_news r ON g.news_id = r.id
                   WHERE g.published >= ? AND g.region = ?
                   ORDER BY r.urgency DESC LIMIT 5""",
                (since, region)
            ).fetchall()
            top_events = [{"news_id": nr["news_id"], "title": nr["title"], "urgency": nr["urgency"]} for nr in news_rows]

            lat = r["latitude"] or 20.0
            lng = r["longitude"] or 0.0
            urgency_score = min(1.0, r["urgency"] / 3.0) if r["urgency"] else 0.5

            regions.append({
                "region": region,
                "lat": lat,
                "lng": lng,
                "news_count": r["cnt"],
                "ai_brief": f"{region} 区域有 {r['cnt']} 条新闻，重点事件请查看详情",
                "urgency_score": urgency_score,
                "hour_bucket": int(time.time()) // 3600 * 3600,
                "hour_label": _hour_label(int(time.time()) // 3600 * 3600),
                "top_events": top_events,
                "computed_by": "realtime",
            })

        return jsonify({"regions": regions, "source": "realtime"})
    finally:
        db.close()


# ── API: Timeline Narrative（时间线因果链 + AI 叙事）─────────

@app.route("/api/timeline_narrative")
def api_timeline_narrative():
    """返回小时级因果链叙事（时间线用）"""
    hours = int(request.args.get("hours", 24))
    since = int(time.time()) - hours * 3600
    current_hour = (int(time.time()) // 3600) * 3600

    db = get_db()
    try:
        # 尝试从 hour_causal_narratives 读取
        rows = db.execute(
            """SELECT id, hour_bucket, ai_chain, ai_summary,
                      total_events, computed_at, computed_by
               FROM hour_causal_narratives
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC""",
            (since,)
        ).fetchall()

        if rows:
            items = []
            for r in rows:
                items.append({
                    "hour":        r["hour_bucket"],
                    "hour_label": _hour_label(r["hour_bucket"]),
                    "ai_summary": r["ai_summary"],
                    "causal_chain": json.loads(r["ai_chain"] or "[]"),
                    "total_events": r["total_events"],
                    "computed_by": r["computed_by"],
                })
            return jsonify({"hours": items, "source": "ai"})

        # 降级：从 event_summaries 实时聚合
        summary_rows = db.execute(
            """SELECT id, hour_bucket, top_events, ai_narrative,
                      event_count, computed_at, computed_by
               FROM event_summaries
               WHERE hour_bucket >= ?
               ORDER BY hour_bucket DESC""",
            (since,)
        ).fetchall()

        items = []
        for r in summary_rows:
            top_events = json.loads(r["top_events"] or "[]")
            # 转换为简化 causal_chain
            chain = [
                {
                    "event": e.get("title", "")[:40],
                    "cause": "新闻事件",
                    "effect": e.get("summary", "")[:30],
                    "news_ids": [e.get("news_id", "")],
                }
                for e in top_events[:3]
            ]
            items.append({
                "hour":        r["hour_bucket"],
                "hour_label": _hour_label(r["hour_bucket"]),
                "ai_summary": r["ai_narrative"] or f"本小时共 {r['event_count']} 条事件",
                "causal_chain": chain,
                "total_events": r["event_count"],
                "computed_by": r["computed_by"],
            })

        return jsonify({"hours": items, "source": "realtime"})
    finally:
        db.close()


@app.route("/api/global_narrative")
def api_global_narrative():
    """返回全局叙事（跨时间/跨区域的关联分析和洞察）"""
    hours = int(request.args.get("hours", 24))

    db = get_db()
    try:
        # 尝试读取最新一条全局叙事
        row = db.execute(
            """SELECT id, generated_at, lookback_hours, news_count,
                      global_view, insights, symbol_network,
                      cross_region_links, time_patterns, computed_by
               FROM global_narratives
               WHERE generated_at >= ?
               ORDER BY generated_at DESC
               LIMIT 1""",
            (int(time.time()) - hours * 3600,)
        ).fetchone()

        if row:
            return jsonify({
                "source": "ai",
                "generated_at": row["generated_at"],
                "lookback_hours": row["lookback_hours"],
                "news_count": row["news_count"],
                "global_view": json.loads(row["global_view"] or "{}"),
                "insights": json.loads(row["insights"] or "[]"),
                "symbol_network": json.loads(row["symbol_network"] or "{}"),
                "cross_region_links": json.loads(row["cross_region_links"] or "[]"),
                "time_patterns": json.loads(row["time_patterns"] or "{}"),
                "computed_by": row["computed_by"],
            })

        return jsonify({"source": "none", "message": "暂无全局叙事数据，请等待 AI 生成"})
    finally:
        db.close()


@app.route("/api/generate_global", methods=["POST"])
def api_generate_global():
    """手动触发全局叙事生成（用于测试）"""
    hours = int(request.args.get("hours", 24))

    import asyncio
    from pipeline.global_narrative import run_global_narrative

    try:
        result = asyncio.run(run_global_narrative(hours))
        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        return jsonify({"success": True, "theme": result["global_view"].get("theme", "N/A")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/global_narrative/history")
def api_global_narrative_history():
    """返回全局叙事历史（最近 N 条）—— 用于追溯连续性"""
    limit = int(request.args.get("limit", 10))

    db = get_db()
    try:
        # 用 PRAGMA 检查是否有 references_history_ids 列
        cols = [r["name"] for r in db.execute("PRAGMA table_info(global_narratives)").fetchall()]
        has_refs = "references_history_ids" in cols

        select_cols = "id, generated_at, lookback_hours, news_count, global_view, insights, computed_by"
        if has_refs:
            select_cols += ", references_history_ids"

        rows = db.execute(
            f"""SELECT {select_cols}
                FROM global_narratives
                ORDER BY generated_at DESC
                LIMIT ?""",
            (limit,)
        ).fetchall()

        history = []
        for r in rows:
            try:
                gv = json.loads(r["global_view"] or "[]")
            except Exception:
                gv = []
            try:
                ins = json.loads(r["insights"] or "[]")
            except Exception:
                ins = []
            try:
                refs = json.loads(r["references_history_ids"]) if has_refs and r["references_history_ids"] else []
            except Exception:
                refs = []
            # 提取每个 viewpoint 的 theme（用于 list 显示）
            themes = []
            if isinstance(gv, list):
                for v in gv[:5]:
                    if isinstance(v, dict):
                        themes.append(v.get("theme", "")[:60])
            history.append({
                "id": r["id"],
                "generated_at": r["generated_at"],
                "lookback_hours": r["lookback_hours"],
                "news_count": r["news_count"],
                "computed_by": r["computed_by"],
                "themes": themes,
                "first_theme": themes[0] if themes else "(无主题)",
                "insight_count": len(ins) if isinstance(ins, list) else 0,
                "references_history_ids": refs,
            })

        return jsonify({
            "ok": True,
            "count": len(history),
            "history": history,
        })
    finally:
        db.close()


# ── Period Insights API（多周期 AI 洞察 + 多空板块） ─────────
@app.route("/api/insights/period", methods=["GET"])
def api_insights_period_get():
    """读周期洞察（缓存优先）。period=daily|3day|weekly|monthly"""
    period = request.args.get("period", "daily")
    import asyncio
    from pipeline.period_insights import get_period_insight
    try:
        result = asyncio.run(get_period_insight(period, force_regenerate=False))
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/insights/period/all", methods=["GET"])
def api_insights_period_all():
    """一次返回 4 个周期"""
    import asyncio
    from pipeline.period_insights import get_all_periods
    try:
        result = asyncio.run(get_all_periods())
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/insights/generate", methods=["POST"])
def api_insights_generate():
    """手动触发重新生成某个周期。period=daily|3day|weekly|monthly"""
    period = request.args.get("period", "daily")
    import asyncio
    from pipeline.period_insights import get_period_insight
    try:
        result = asyncio.run(get_period_insight(period, force_regenerate=True))
        if result.get("ok"):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/insights/history", methods=["GET"])
def api_insights_history():
    """历史洞察列表。period=daily|3day|weekly|monthly（不传则全部）&limit=N"""
    period = request.args.get("period")
    limit = int(request.args.get("limit", 20))
    import asyncio
    from pipeline.period_insights import get_period_history
    try:
        result = asyncio.run(get_period_history(period, limit))
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/insights/compare", methods=["GET"])
def api_insights_compare():
    """对比最新 vs 上一期（连续性 diff）。period=daily|3day|weekly|monthly"""
    period = request.args.get("period", "daily")
    import asyncio
    from pipeline.period_insights import get_period_compare
    try:
        result = asyncio.run(get_period_compare(period))
        if not result.get("ok"):
            return jsonify(result), 400 if "error" in result and result.get("error") != "no_history" else 200
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Pages ─────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")

@app.route("/analytics")
def analytics():
    return send_from_directory(WEB_DIR, "analytics.html")

@app.route("/map")
def map_page():
    return send_from_directory(WEB_DIR, "map.html")

@app.route("/timeline")
def timeline_page():
    return send_from_directory(WEB_DIR, "timeline.html")

@app.route("/graph")
def graph_page():
    return send_from_directory(WEB_DIR, "graph.html")

@app.route("/graph3d")
def graph3d_page():
    return send_from_directory(WEB_DIR, "graph3d.html")

@app.route("/system")
def system_page():
    return send_from_directory(WEB_DIR, "system.html")

@app.route("/backup")
def backup_page():
    return send_from_directory(WEB_DIR, "backup.html")

@app.route("/config/backfill")
def backfill_config_page():
    return send_from_directory(WEB_DIR, "config_backfill.html")

@app.route("/history")
def history_page():
    return send_from_directory(WEB_DIR, "history.html")

def _free_port(port: int):
    """如果端口被占用，先杀掉占用进程"""
    import subprocess, signal
    result = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split()
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
            print(f"[server] 已终止占用端口 {port} 的进程 PID={pid}")
        except PermissionError:
            print(f"[server] 无权限终止占用端口 {port} 的进程 PID={pid}，跳过")
        except ProcessLookupError:
            pass
    if pids:
        import time as _time
        _time.sleep(0.5)


# ── Backup 业务逻辑 ──
def _do_backup() -> dict:
    """执行一次备份（在线热备 + gzip 压缩 + 清理过期）。返回元数据。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(BACKUP_DIR, f"{BACKUP_PREFIX}{ts}.db")
    gz_path = f"{raw_path}.gz"

    # SQLite 在线热备（不锁表）
    src = sqlite3.connect(_settings.DB_PATH)
    dst = sqlite3.connect(raw_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

    # gzip 压缩
    with open(raw_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(raw_path)

    raw_size = os.path.getsize(gz_path)
    _backup_schedule["last_run"] = datetime.now().isoformat(timespec="seconds")
    return {
        "ok": True,
        "file": os.path.basename(gz_path),
        "size_mb": round(raw_size / 1024 / 1024, 2),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _list_backups() -> list[dict]:
    """列出所有备份"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not (f.startswith(BACKUP_PREFIX) and f.endswith(".db.gz")):
            continue
        p = os.path.join(BACKUP_DIR, f)
        st = os.stat(p)
        out.append({
            "name": f,
            "size_mb": round(st.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "age_days": round((time.time() - st.st_mtime) / 86400, 1),
        })
    return out


def _restore_backup(filename: str) -> dict:
    """从指定备份恢复。安全机制：恢复前先自动备份当前 DB。"""
    if not filename or "/" in filename or ".." in filename:
        return {"ok": False, "error": "invalid filename"}
    gz_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(gz_path):
        return {"ok": False, "error": "file not found"}
    if not (filename.startswith(BACKUP_PREFIX) and filename.endswith(".db.gz")):
        return {"ok": False, "error": "invalid file format"}

    # 1. 恢复前自动备份当前 DB（防恢复出错）
    pre_meta = _do_backup()
    pre_meta["file"] = "pre_restore_" + pre_meta["file"]

    # 2. 解压覆盖
    with gzip.open(gz_path, "rb") as f_in, open(_settings.DB_PATH, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    return {
        "ok": True,
        "restored_from": filename,
        "pre_restore_backup": pre_meta["file"],
    }


def _delete_backup(filename: str) -> dict:
    if not filename or "/" in filename or ".." in filename:
        return {"ok": False, "error": "invalid filename"}
    p = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(p):
        return {"ok": False, "error": "file not found"}
    if not (filename.startswith(BACKUP_PREFIX) and filename.endswith(".db.gz")):
        return {"ok": False, "error": "invalid file format"}
    os.remove(p)
    return {"ok": True}


# ── Backup API ──
@app.route("/api/backup/list")
def api_backup_list():
    backups = _list_backups()
    total_size = sum(b["size_mb"] for b in backups)
    return jsonify({
        "backups": backups,
        "count": len(backups),
        "total_size_mb": round(total_size, 2),
        "backup_dir": BACKUP_DIR,
    })


@app.route("/api/backup/create", methods=["POST"])
def api_backup_create():
    try:
        meta = _do_backup()
        return jsonify(meta)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backup/restore", methods=["POST"])
def api_backup_restore():
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "filename required"}), 400
    try:
        return jsonify(_restore_backup(filename))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backup/<path:filename>", methods=["DELETE"])
def api_backup_delete(filename):
    try:
        return jsonify(_delete_backup(filename))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backup/schedule", methods=["GET"])
def api_backup_schedule_get():
    """获取备份计划状态"""
    enabled = _backup_schedule["enabled"]
    hour = _backup_schedule["hour"]
    last_run = _backup_schedule["last_run"]
    # 计算下次运行时间
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return jsonify({
        "enabled": enabled,
        "hour": hour,
        "last_run": last_run,
        "next_run": next_run.isoformat(timespec="seconds"),
        "db_path": _settings.DB_PATH,
        "backup_dir": BACKUP_DIR,
    })


@app.route("/api/backup/schedule", methods=["POST"])
def api_backup_schedule_set():
    """设置备份计划（保留策略已禁用：所有备份永不自动删除）"""
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        _backup_schedule["enabled"] = bool(data["enabled"])
    if "hour" in data:
        h = int(data["hour"])
        if not (0 <= h <= 23):
            return jsonify({"ok": False, "error": "hour must be 0-23"}), 400
        _backup_schedule["hour"] = h
    return jsonify({"ok": True, **_backup_schedule})


@app.route("/api/backup/info", methods=["GET"])
def api_backup_info():
    """DB & 备份路径 + 当前状态（不修改任何文件）"""
    # DB 大小
    db_size_mb = 0.0
    db_row_count = 0
    db_exists = os.path.exists(_settings.DB_PATH)
    if db_exists:
        db_size_mb = round(os.path.getsize(_settings.DB_PATH) / 1024 / 1024, 2)
        try:
            conn = sqlite3.connect(_settings.DB_PATH)
            try:
                db_row_count = conn.execute("SELECT COUNT(*) FROM raw_news").fetchone()[0]
            except sqlite3.OperationalError:
                # 表不存在（DB 刚 init 还没建表）
                db_row_count = 0
            finally:
                conn.close()
        except Exception:
            db_row_count = 0

    # 最近一次备份
    last_backup = None
    if os.path.isdir(BACKUP_DIR):
        backups = [
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith(BACKUP_PREFIX) and f.endswith(".db.gz")
        ]
        if backups:
            latest = max(backups, key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)))
            p = os.path.join(BACKUP_DIR, latest)
            st = os.stat(p)
            last_backup = {
                "file": latest,
                "size_mb": round(st.st_size / 1024 / 1024, 2),
                "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }

    return jsonify({
        "db_path":     _settings.DB_PATH,
        "db_exists":   db_exists,
        "db_size_mb":  db_size_mb,
        "db_row_count": db_row_count,
        "backup_dir":  BACKUP_DIR,
        "last_backup": last_backup,
        "schedule": {
            "enabled":  _backup_schedule["enabled"],
            "hour":     _backup_schedule["hour"],
            "last_run": _backup_schedule["last_run"],
        },
    })


# ── 备份 scheduler 线程（每分钟检查，到点跑）──
def _backup_scheduler_loop():
    """独立线程：每 30s 检查一次，到 hour:00 跑备份"""
    last_run_hour_key = None
    while True:
        try:
            if _backup_schedule["enabled"]:
                now = datetime.now()
                hour_key = f"{now.year}-{now.month}-{now.day}-{now.hour}"
                if now.hour == _backup_schedule["hour"] and now.minute < 5 and hour_key != last_run_hour_key:
                    last_run_hour_key = hour_key
                    print(f"[backup-scheduler] 触发定时备份 @ {now.isoformat(timespec='seconds')}")
                    meta = _do_backup()
                    print(f"[backup-scheduler] 完成: {meta['file']} ({meta['size_mb']} MB)")
        except Exception as e:
            print(f"[backup-scheduler] 错误: {e}")
        time.sleep(30)


# 启动 scheduler 线程
_backup_scheduler_thread = threading.Thread(target=_backup_scheduler_loop, daemon=True)
_backup_scheduler_thread.start()


# ── Backfill 任务管理 ──
BACKFILL_SCRIPT = os.path.join(os.path.dirname(WEB_DIR), "scripts", "backfill_story_body.py")
BACKFILL_LOG = os.path.join(os.path.dirname(WEB_DIR), "logs", "backfill.log")
BACKFILL_LOCK = "/tmp/tvnews_backfill.lock"
_backfill_state = {
    "status": "idle",   # idle / running / done / error
    "pid": None,
    "limit": None,
    "delay": None,
    "started_at": None,
    "ended_at": None,
    "exit_code": None,
    "log_tail": [],
    "pending_before": 0,
    "pending_after": 0,
}


def _backfill_pending() -> int:
    """查询当前未回填条数"""
    db = sqlite3.connect(_settings.DB_PATH)
    try:
        n = db.execute("SELECT COUNT(*) FROM raw_news WHERE story_body IS NULL OR length(story_body) < 5").fetchone()[0]
        return n
    finally:
        db.close()


@app.route("/api/backfill/preview")
def api_backfill_preview():
    """查看当前未回填条数 + 上次状态"""
    pending = _backfill_pending()
    return jsonify({
        "pending": pending,
        "state": _backfill_state,
    })


@app.route("/api/backfill/run", methods=["POST"])
def api_backfill_run():
    """启动后台回填任务（独立子进程）"""
    if os.path.exists(BACKFILL_LOCK):
        return jsonify({"ok": False, "error": "已有回填任务在运行（lockfile 存在）"}), 400

    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit", 500))
        delay = float(data.get("delay", 0.8))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "limit / delay 必须是数字"}), 400
    if limit < 1 or limit > 10000:
        return jsonify({"ok": False, "error": "limit 必须在 1-10000"}), 400
    if delay < 0.1 or delay > 10:
        return jsonify({"ok": False, "error": "delay 必须在 0.1-10 秒"}), 400

    if not os.path.exists(BACKFILL_SCRIPT):
        return jsonify({"ok": False, "error": f"脚本不存在: {BACKFILL_SCRIPT}"}), 500

    try:
        os.makedirs(os.path.dirname(BACKFILL_LOG), exist_ok=True)
        with open(BACKFILL_LOCK, "w") as f:
            f.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
        log_f = open(BACKFILL_LOG, "a", buffering=1)
        log_f.write(f"\n=== 启动回填 @ {datetime.now().isoformat()} (limit={limit}, delay={delay}) ===\n")
        proc = subprocess.Popen(
            [sys.executable, BACKFILL_SCRIPT, "--limit", str(limit), "--delay", str(delay)],
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _backfill_state.update({
            "status": "running",
            "pid": proc.pid,
            "limit": limit,
            "delay": delay,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "ended_at": None,
            "exit_code": None,
            "log_tail": [],
            "pending_before": _backfill_pending(),
        })
        return jsonify({"ok": True, "pid": proc.pid, "limit": limit, "delay": delay, "pending_before": _backfill_state["pending_before"]})
    except Exception as e:
        if os.path.exists(BACKFILL_LOCK):
            try: os.remove(BACKFILL_LOCK)
            except OSError: pass
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backfill/status")
def api_backfill_status():
    """当前回填任务状态 + 进度"""
    # 检查 PID 是否还活
    if _backfill_state.get("pid"):
        try:
            os.kill(_backfill_state["pid"], 0)  # 信号 0 = 检查存活
            still_running = True
        except (ProcessLookupError, PermissionError):
            still_running = False
        if not still_running and _backfill_state["status"] == "running":
            _backfill_state["status"] = "done"
            _backfill_state["ended_at"] = datetime.now().isoformat(timespec="seconds")
            _backfill_state["pending_after"] = _backfill_pending()
            if os.path.exists(BACKFILL_LOCK):
                try: os.remove(BACKFILL_LOCK)
                except OSError: pass
    # 读 log 尾部
    if os.path.exists(BACKFILL_LOG):
        try:
            with open(BACKFILL_LOG, "r") as f:
                lines = f.readlines()
                _backfill_state["log_tail"] = lines[-30:]
        except Exception:
            pass
    return jsonify(_backfill_state)


@app.route("/api/backfill/stop", methods=["POST"])
def api_backfill_stop():
    """强制停止当前回填任务"""
    pid = _backfill_state.get("pid")
    if not pid or _backfill_state["status"] != "running":
        return jsonify({"ok": False, "error": "没有运行中的任务"}), 400
    try:
        os.kill(pid, 15)  # SIGTERM
    except ProcessLookupError:
        pass
    if os.path.exists(BACKFILL_LOCK):
        try: os.remove(BACKFILL_LOCK)
        except OSError: pass
    _backfill_state["status"] = "stopped"
    _backfill_state["ended_at"] = datetime.now().isoformat(timespec="seconds")
    return jsonify({"ok": True})


# ── API: AI 管理状态（只读 — 永不出 API key 原值）─────────
@app.route("/api/system/ai_status")
def api_system_ai_status():
    """AI 洞察管理的实时状态（前端 /system + /config/backfill 共用）。

    安全：永远不返回 API key 原值。只返回是否已配置 + 长度 + 来源描述。
    """
    api_key = (_settings.MINIMAX_API_KEY or "").strip()
    api_key_set = bool(api_key)
    # 仅暴露长度和首/末 4 位掩码（便于用户确认是同一把 key）
    api_key_masked = None
    if api_key_set and len(api_key) >= 8:
        api_key_masked = f"{api_key[:4]}…{api_key[-4:]}（共 {len(api_key)} 字符）"
    elif api_key_set:
        api_key_masked = f"（共 {len(api_key)} 字符）"

    # period_insights: 每周期最近一次生成时间
    periods = {}
    try:
        db = get_db()
        for period in ("daily", "3day", "weekly", "monthly"):
            row = db.execute(
                """SELECT generated_at, period_start, news_count, computed_by
                   FROM period_insights
                   WHERE period = ?
                   ORDER BY generated_at DESC LIMIT 1""",
                (period,),
            ).fetchone()
            if row:
                periods[period] = {
                    "generated_at": int(row["generated_at"]),
                    "period_start": int(row["period_start"]),
                    "news_count":   int(row["news_count"]),
                    "provider":     row["computed_by"],
                }
            else:
                periods[period] = None
    except Exception:
        pass

    # global_narratives: 最近一次
    last_global = None
    try:
        db = get_db()
        # 先看 columns
        cols = [r["name"] for r in db.execute("PRAGMA table_info(global_narratives)").fetchall()]
        # 尝试几个可能的列名
        gen_col = "generated_at" if "generated_at" in cols else ("ts" if "ts" in cols else None)
        prov_col = "computed_by" if "computed_by" in cols else ("provider" if "provider" in cols else None)
        if gen_col:
            sql = f"SELECT {gen_col} AS ga"
            if prov_col: sql += f", {prov_col} AS prov"
            sql += " FROM global_narratives"
            sql += f" ORDER BY {gen_col} DESC LIMIT 1"
            row = db.execute(sql).fetchone()
            if row:
                last_global = {"generated_at": int(row["ga"])}
                if prov_col and row["prov"]:
                    last_global["provider"] = row["prov"]
    except Exception:
        pass

    # 解析 .env 文件路径（供前端展示「修改位置」提示）
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, ".env")
    env_exists = os.path.exists(env_path)

    return jsonify({
        "provider":        "MiniMax",
        "model":           _settings.MINIMAX_MODEL,
        "base_url":        _settings.MINIMAX_BASE_URL,
        "api_key_set":     api_key_set,
        "api_key_masked":  api_key_masked,
        "api_key_source":  ".env (MINIMAX_API_KEY)",
        "api_key_path":    env_path,
        "env_exists":      env_exists,
        "periods":         periods,
        "last_global_narrative": last_global,
        "note":            "API key 配置在 .env 文件，修改后需重启 News/Web 服务才能生效。",
    })


if __name__ == "__main__":
    PORT = 5888
    _free_port(PORT)
    print(f"Dashboard:  http://localhost:{PORT}")
    print(f"Analytics:  http://localhost:{PORT}/analytics")
    print(f"Map:        http://localhost:{PORT}/map")
    print(f"Timeline:   http://localhost:{PORT}/timeline")
    print(f"Graph:      http://localhost:{PORT}/graph")
    print(f"Backup:     http://localhost:{PORT}/backup")
    app.run(host="0.0.0.0", port=PORT, debug=False)
