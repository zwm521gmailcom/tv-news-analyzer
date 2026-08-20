"""
Period Insights — 多周期 AI 洞察 + 多空板块预测
使用 MiniMax M3，支持 4 个周期：daily / 3day / weekly / monthly

v2 增强：
- 多尺度历史 context：每个周期生成时拉上期同周期 + 子周期（weekly 看 7 个 daily；monthly 看 4 个 weekly）
- 连续性 prompt：AI 标注每个 theme 的 status (new/continued/resolved)
- history 表 append-only：保留所有生成历史（period_insights_history）
- diff 元数据：new_themes / continued_themes / resolved_themes / trend
- API：get_period_history / get_period_compare

v3 调整（按用户要求"纯同周期"）：
- HISTORY_CONTEXT_RULES 改为纯同周期：daily 看前 3 个 daily，3day 看前 2 个 3day
- weekly 看前 2 个 weekly，monthly 看前 2 个 monthly
- 不再混合子周期（避免 AI 看到 7 个 daily 反而被淹没）
- 隔离：本模块与 global_narrative 完全独立，不共享 context

设计原则：
- 幂等：相同 (period, period_start) 不会重复生成（除非 force_regenerate）
- 缓存：最新结果存 period_insights 表；历史 append 到 period_insights_history
- 降级：MiniMax 不可用时返回 ok=False + error，不静默伪造
- 数据约束：当实际数据跨度 < period 设定时（DB 不足 30 天），在 prompt 里显式提示
- 隔离：与 AI 全局叙事（global_narrative）完全独立，两套历史各自保留
"""

import asyncio
import json
import time
from typing import Optional

from db.database import get_db
from config import settings

# 复用 global_narrative 的 MiniMax 工具（已验证可工作）
from pipeline.global_narrative import _minimax_request, _extract_json, minimax_available


# ── 周期配置 ─────────────────────────────────────────────
PERIODS = {
    "daily":   {"lookback_secs": 1 * 86400,   "label": "过去 24 小时"},
    "3day":    {"lookback_secs": 3 * 86400,   "label": "过去 3 天"},
    "weekly":  {"lookback_secs": 7 * 86400,   "label": "过去 7 天"},
    "monthly": {"lookback_secs": 30 * 86400,  "label": "过去 30 天"},
}

# 每个周期 prompt 强度不同（summary 字数严格控制，防止 M3 写超长文）
# 主题/多空板块数量已经按用户要求增加（v2）
PERIOD_CONFIG = {
    "daily":   {"summary_words": 200,  "themes_n": 5,  "bull_n": 3, "bear_n": 3, "news_text_limit": 30},
    "3day":    {"summary_words": 300,  "themes_n": 7,  "bull_n": 4, "bear_n": 4, "news_text_limit": 50},
    "weekly":  {"summary_words": 500,  "themes_n": 8,  "bull_n": 5, "bear_n": 5, "news_text_limit": 70},
    "monthly": {"summary_words": 700,  "themes_n": 10, "bull_n": 6, "bear_n": 6, "news_text_limit": 90},
}

# 纯同周期历史 context 策略（v3）：每个周期只看前 N 个同 period 历史
# 不再混合子周期（避免 daily 数量过多淹没 AI 上下文）
# 与 AI 全局叙事（global_narrative）隔离，history 表独立
HISTORY_CONTEXT_RULES = {
    "daily":   {"prior_count": 3},   # 前 3 个 daily 洞察
    "3day":    {"prior_count": 2},   # 前 2 个 3day 洞察
    "weekly":  {"prior_count": 2},   # 前 2 个 weekly 洞察
    "monthly": {"prior_count": 2},   # 前 2 个 monthly 洞察
}


# ── 数据聚合 ─────────────────────────────────────────────
async def _aggregate_period(period_start: int, period_end: int) -> dict:
    """SQL 聚合一个周期的数据：market / provider / symbol / urgency"""
    async with get_db() as db:
        # total
        cur = await db.execute(
            "SELECT COUNT(*) FROM raw_news WHERE published >= ? AND published < ?",
            (period_start, period_end)
        )
        total = (await cur.fetchone())[0]

        # market
        cur = await db.execute(
            "SELECT market, COUNT(*) c FROM raw_news WHERE published >= ? AND published < ? GROUP BY market",
            (period_start, period_end)
        )
        market = {r[0]: r[1] for r in await cur.fetchall()}

        # provider (top 10)
        cur = await db.execute(
            """SELECT provider, COUNT(*) c FROM raw_news
               WHERE published >= ? AND published < ? AND provider IS NOT NULL
               GROUP BY provider ORDER BY c DESC LIMIT 10""",
            (period_start, period_end)
        )
        provider = [(r[0] or "Unknown", r[1]) for r in await cur.fetchall()]

        # top symbols（symbol 列是 JSON 字符串，需解析）
        cur = await db.execute(
            """SELECT symbols FROM raw_news
               WHERE published >= ? AND published < ?
                 AND symbols IS NOT NULL AND symbols != '[]'""",
            (period_start, period_end)
        )
        rows = await cur.fetchall()
        symbol_count = {}
        for r in rows:
            try:
                syms = json.loads(r[0]) if isinstance(r[0], str) else (r[0] or [])
                for s in syms:
                    if not s:
                        continue
                    # 格式: "BINANCE:BTCUSDT" -> 取 "BTCUSDT"
                    parts = s.split(":")
                    ticker = parts[-1].strip() if len(parts) > 1 else s.strip()
                    if ticker:
                        symbol_count[ticker] = symbol_count.get(ticker, 0) + 1
            except Exception:
                pass
        top_symbols = sorted(symbol_count.items(), key=lambda x: -x[1])[:10]

        # urgency 平均
        cur = await db.execute(
            "SELECT AVG(urgency) FROM raw_news WHERE published >= ? AND published < ?",
            (period_start, period_end)
        )
        urgency_avg = (await cur.fetchone())[0] or 1.0

    return {
        "news_count": total,
        "market": market,
        "provider": provider,
        "top_symbols": top_symbols,
        "urgency_avg": urgency_avg,
    }


async def _fetch_news_text(period_start: int, period_end: int, limit: int = 50) -> str:
    """按紧急度 + 时间取 top N 新闻，拼成文本（每条带时间戳）"""
    async with get_db() as db:
        cur = await db.execute(
            """SELECT provider, title, short_desc, urgency, market, published
               FROM raw_news
               WHERE published >= ? AND published < ?
               ORDER BY urgency DESC, published DESC
               LIMIT ?""",
            (period_start, period_end, limit)
        )
        rows = await cur.fetchall()
    lines = []
    for r in rows:
        provider = r[0] or "Unknown"
        title = (r[1] or "")[:100]
        short = (r[2] or "")[:80]
        market = r[4] or "unknown"
        ts = r[5] or 0
        # 时间戳格式：相对当前时间（人类可读）+ 绝对日期（避免歧义）
        age_sec = max(0, int(time.time()) - int(ts))
        if age_sec < 3600:
            rel = f"{age_sec // 60}分钟前"
        elif age_sec < 86400:
            rel = f"{age_sec // 3600}小时前"
        else:
            rel = f"{age_sec // 86400}天前"
        abs_ts = time.strftime("%m-%d %H:%M", time.localtime(ts))
        lines.append(f"- [{abs_ts} · {rel}] [{provider}/{market}] {title}")
        if short and short != title[:80]:
            lines.append(f"  摘要: {short}")
    return "\n".join(lines)


# ── 历史 context ──────────────────────────────────────────
async def _fetch_history(period: str) -> dict:
    """从 history 表拉"前 N 个同 period 历史"，供 prompt 用。

    返回：
      {
        "prior": { 完整 latest prior 一行 } | None,    # 第一个（最近一个）
        "all_priors": [ { ... } x prior_count ],        # 全部 N 个（倒序）
      }
    """
    rules = HISTORY_CONTEXT_RULES[period]
    prior_count = rules["prior_count"]
    out = {"prior": None, "all_priors": []}

    async with get_db() as db:
        # 拉前 N 个同 period 历史（按时间倒序，最新在前）
        cur = await db.execute(
            """SELECT id, period, period_start, period_end, news_count,
                      ai_summary, ai_themes, bullish_sectors, bearish_sectors,
                      generated_at, references_prior_id, trend
               FROM period_insights_history
               WHERE period = ?
               ORDER BY generated_at DESC LIMIT ?""",
            (period, prior_count)
        )
        rows = await cur.fetchall()
        for r in rows:
            out["all_priors"].append(_row_to_prior_dict(r))
        # 第一个是最近一个 = "prior"
        if out["all_priors"]:
            out["prior"] = out["all_priors"][0]

    return out


def _row_to_prior_dict(row) -> dict:
    """history 表行 → 完整 prior dict（含 themes / sectors）"""
    return {
        "id": row[0],
        "period": row[1],
        "period_start": row[2],
        "period_end": row[3],
        "news_count": row[4],
        "ai_summary": row[5] or "",
        "ai_themes": json.loads(row[6]) if row[6] else [],
        "bullish_sectors": json.loads(row[7]) if row[7] else [],
        "bearish_sectors": json.loads(row[8]) if row[8] else [],
        "generated_at": row[9],
        "references_prior_id": row[10],
        "trend": row[11] or "stable",
    }




def _format_history_context(history: dict) -> str:
    """把 history dict 拼成 prompt 文本段。

    v3：纯同周期历史，列出全部 N 个 prior（不只是 latest 1 个）。
    每个 prior 都展开完整 details（summary + themes + sectors + trend），
    因为 prior 数量受 HISTORY_CONTEXT_RULES 限制（≤3），不会过长。
    """
    lines = []
    all_priors = history.get("all_priors", [])

    if not all_priors:
        return "（暂无历史洞察，这是首次生成）"

    for i, prior in enumerate(all_priors):
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(prior["generated_at"]))
        period_label = prior["period"]
        # 第 1 个标"上一期"（最新），后面标"第 N 期前"
        if i == 0:
            title = f"【上一期{period_label}洞察（{ts}生成，{prior['news_count']}条新闻）】"
        else:
            title = f"【{period_label}洞察 #{i+1}（{ts}生成，{prior['news_count']}条新闻）】"
        lines.append(title)
        lines.append(f"总结：{prior['ai_summary']}")
        # themes（带 status 标注）
        themes_lines = []
        for t in prior["ai_themes"]:
            status = t.get("status", "")
            tag = {"new": "🆕新", "continued": "🔁延续", "resolved": "✅解决"}.get(status, "•")
            themes_lines.append(f"  {tag} {t.get('title', '')}：{t.get('detail', '')[:60]}")
        if themes_lines:
            lines.append("主题：")
            lines.extend(themes_lines)
        # 看多 / 看空
        if prior["bullish_sectors"]:
            bull = [f"{s.get('sector', '')}({s.get('confidence', 0)})" for s in prior["bullish_sectors"]]
            lines.append(f"看多板块：{', '.join(bull)}")
        if prior["bearish_sectors"]:
            bear = [f"{s.get('sector', '')}({s.get('confidence', 0)})" for s in prior["bearish_sectors"]]
            lines.append(f"看空板块：{', '.join(bear)}")
        lines.append(f"整体趋势：{prior.get('trend', 'stable')}")
        lines.append("")

    return "\n".join(lines)


# ── Prompt 构建 ──────────────────────────────────────────
def _build_period_prompt(period: str, agg: dict, news_text: str,
                        data_span_days: float, db_actual_span_days: float,
                        history_text: str) -> str:
    cfg = PERIOD_CONFIG[period]
    period_label = PERIODS[period]["label"]

    # 数据不足时显式标注
    data_note = ""
    if data_span_days < db_actual_span_days:
        data_note = (
            f"\n【重要】本周期要求 {data_span_days:.0f} 天数据，"
            f"但 DB 实际只有 {db_actual_span_days:.1f} 天数据。"
            f"请基于现有数据做分析，并在 summary 开头注明此限制。"
        )
    elif data_span_days > db_actual_span_days * 1.5:
        data_note = (
            f"\n【提示】本周期要求 {data_span_days:.0f} 天数据，"
            f"DB 实际 {db_actual_span_days:.1f} 天，"
            f"可视为 {data_span_days:.0f} 天窗口里 DB 覆盖的所有数据。"
        )

    return f"""你是专业的金融市场分析师，正在生成{period_label}的【连续性】洞察。

【历史洞察上下文】（必须基于这些做出连续性分析）
{history_text}

【数据概况 - 本期】
- 市场分布：{json.dumps(agg['market'], ensure_ascii=False)}
- Top 来源：{json.dumps(agg['provider'][:5], ensure_ascii=False)}
- Top 交易标的：{json.dumps([s for s, _ in agg['top_symbols'][:10]], ensure_ascii=False)}
- 平均紧急度：{agg['urgency_avg']:.2f}（1=低 2=中 3=高）{data_note}

【新闻列表 - 最多 {cfg['news_text_limit']} 条（每条带 [MM-DD HH:MM · X小时前] 时间戳）】
{news_text}

【时效校验硬规则】
1. 新闻已按"紧急度+时间"排序，最新在前。每条带 [MM-DD HH:MM · X小时前/天前] 时间戳
2. 引用具体数字/价格时，必须用"该数字出现的新闻时间"来定位，不要把过时的数字当作当前价
3. 如果多条新闻出现的同一标的数字差异大（如黄金 2400 vs 4500），以最新一条为准，旧数字仅作为对比/历史
4. 做"X 将涨到 Y"的预测时，Y 应基于最新数字 + 当前趋势，不要引用 1 周前的旧价位

【任务】输出严格 JSON（不要任何其他内容、说明、前后缀）：

{{
  "summary": "中文分析 {cfg['summary_words']}字内。必须：(1) 引用上期关键主题，说明延续/反转；(2) 概括本期新出现核心变化；(3) 引用具体公司/数字/事件；(4) 数字必须锚定到具体新闻时间。⚠️ 中文引用语必须用「」或『』包裹，不要用英文双引号 \"，避免破坏 JSON 格式",
  "themes": [
    {{"title": "主题（15字内）", "detail": "30字内说明", "status": "new|continued|resolved"}} x {cfg['themes_n']}
  ],
  "bullish_sectors": [
    {{"sector": "板块", "confidence": 0-100, "reason": "30字内", "status": "new|continued|reversed"}} x {cfg['bull_n']}
  ],
  "bearish_sectors": [
    {{"sector": "板块", "confidence": 0-100, "reason": "30字内", "status": "new|continued|reversed"}} x {cfg['bear_n']}
  ],
  "trend": "整体市场情绪相对上期：up|down|stable|mixed"
}}

【status 字段规则】
- new：本期首次出现的主题/板块判断
- continued：从上期延续的主线（同一方向）
- resolved：上期提出但本期已无相关信号（消退）
- reversed：上期看多但本期反向（板块级别才有）

【严格要求】
1. summary 严格控制在 {cfg['summary_words']}字内，引用具体公司/数字/事件
2. themes 不重复，必须覆盖宏观/行业/标的/地缘/政策 等不同维度
3. 看多看空板块必须基于本期实际新闻情绪判断（不是凭感觉）
4. confidence 0-100：高>70，中40-70，低<40
5. 至少 30% 的 themes 应标记 continued 或 resolved（保证连续性）
6. 只输出 JSON，不要任何其他文字"""


# ── 调用 MiniMax ─────────────────────────────────────────
async def _generate_period_insight(period: str, period_start: int, period_end: int) -> dict:
    """对一个周期调 MiniMax 生成洞察（带历史 context）"""
    if not await minimax_available():
        return {"ok": False, "error": "minimax_unavailable", "news_count": 0}

    agg = await _aggregate_period(period_start, period_end)
    if agg["news_count"] == 0:
        return {"ok": False, "error": "no_data_in_period", "news_count": 0}

    cfg = PERIOD_CONFIG[period]
    news_text = await _fetch_news_text(period_start, period_end, limit=cfg["news_text_limit"])

    # 拉多尺度历史 context
    history = await _fetch_history(period)
    history_text = _format_history_context(history)

    # 计算实际数据跨度（DB 最早数据到现在）
    async with get_db() as db:
        cur = await db.execute("SELECT MIN(published), MAX(published) FROM raw_news")
        row = await cur.fetchone()
    if row and row[0] and row[1]:
        db_actual_span_days = (row[1] - row[0]) / 86400.0
    else:
        db_actual_span_days = 0.0
    data_span_days = (period_end - period_start) / 86400.0

    prompt = _build_period_prompt(
        period, agg, news_text, data_span_days, db_actual_span_days, history_text
    )

    try:
        raw = await _minimax_request(prompt, max_tokens=12000, temperature=0.3, timeout=240)
    except Exception as e:
        return {"ok": False, "error": f"minimax_call_failed: {e}", "news_count": agg["news_count"]}

    parsed = _extract_json(raw)
    if not parsed or not isinstance(parsed, dict):
        return {
            "ok": False,
            "error": "json_parse_failed",
            "news_count": agg["news_count"],
            "raw_preview": raw[:200] if raw else "",
        }

    return {
        "ok": True,
        "summary": parsed.get("summary", ""),
        "themes": parsed.get("themes", []),
        "bullish_sectors": parsed.get("bullish_sectors", []),
        "bearish_sectors": parsed.get("bearish_sectors", []),
        "trend": parsed.get("trend", "stable"),
        "agg": agg,
        "data_span_days": data_span_days,
        "db_actual_span_days": db_actual_span_days,
        "history_prior_id": history.get("prior", {}).get("id") if history.get("prior") else None,
    }


# ── 缓存读写 ─────────────────────────────────────────────
async def _save_period_insight(period: str, period_start: int, period_end: int, gen: dict) -> None:
    """写到两张表：period_insights（最新快照）+ period_insights_history（append）"""
    if not gen.get("ok"):
        return

    # 1. 写 period_insights（覆盖最新）
    async with get_db() as db:
        await db.execute(
            """INSERT OR REPLACE INTO period_insights
               (period, period_start, period_end, news_count,
                market_breakdown, provider_breakdown, symbol_top, urgency_avg,
                ai_summary, ai_themes, bullish_sectors, bearish_sectors,
                agent_score, generated_at, computed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                period, period_start, period_end, gen["agg"]["news_count"],
                json.dumps(gen["agg"]["market"], ensure_ascii=False),
                json.dumps(gen["agg"]["provider"], ensure_ascii=False),
                json.dumps(gen["agg"]["top_symbols"], ensure_ascii=False),
                gen["agg"]["urgency_avg"],
                gen.get("summary", ""),
                json.dumps(gen.get("themes", []), ensure_ascii=False),
                json.dumps(gen.get("bullish_sectors", []), ensure_ascii=False),
                json.dumps(gen.get("bearish_sectors", []), ensure_ascii=False),
                0.0,
                int(time.time()),
                "minimax",
            )
        )
        # 2. 写 period_insights_history（append）
        # diff 元数据
        themes = gen.get("themes", [])
        new_themes = [t["title"] for t in themes if t.get("status") == "new"]
        continued_themes = [t["title"] for t in themes if t.get("status") == "continued"]
        resolved_themes = [t["title"] for t in themes if t.get("status") == "resolved"]
        trend = gen.get("trend", "stable")

        cur = await db.execute(
            """INSERT INTO period_insights_history
               (period, period_start, period_end, news_count,
                market_breakdown, provider_breakdown, symbol_top, urgency_avg,
                ai_summary, ai_themes, bullish_sectors, bearish_sectors,
                agent_score, generated_at, computed_by,
                references_prior_id, new_themes, continued_themes, resolved_themes, trend)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                period, period_start, period_end, gen["agg"]["news_count"],
                json.dumps(gen["agg"]["market"], ensure_ascii=False),
                json.dumps(gen["agg"]["provider"], ensure_ascii=False),
                json.dumps(gen["agg"]["top_symbols"], ensure_ascii=False),
                gen["agg"]["urgency_avg"],
                gen.get("summary", ""),
                json.dumps(themes, ensure_ascii=False),
                json.dumps(gen.get("bullish_sectors", []), ensure_ascii=False),
                json.dumps(gen.get("bearish_sectors", []), ensure_ascii=False),
                0.0,
                int(time.time()),
                "minimax",
                gen.get("history_prior_id"),
                json.dumps(new_themes, ensure_ascii=False),
                json.dumps(continued_themes, ensure_ascii=False),
                json.dumps(resolved_themes, ensure_ascii=False),
                trend,
            )
        )
        await db.commit()
        return cur.lastrowid  # 新插入的 history id


async def _read_period_insight(period: str) -> Optional[dict]:
    """读最新一条 period_insight（按 period_start desc 取最近一条）"""
    async with get_db() as db:
        cur = await db.execute(
            """SELECT period_start, period_end, news_count,
                      market_breakdown, provider_breakdown, symbol_top, urgency_avg,
                      ai_summary, ai_themes, bullish_sectors, bearish_sectors,
                      agent_score, generated_at, computed_by
               FROM period_insights
               WHERE period = ?
               ORDER BY period_start DESC LIMIT 1""",
            (period,)
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "period": period,
        "period_start": row[0],
        "period_end": row[1],
        "news_count": row[2],
        "market_breakdown": json.loads(row[3]) if row[3] else {},
        "provider_breakdown": json.loads(row[4]) if row[4] else [],
        "symbol_top": json.loads(row[5]) if row[5] else [],
        "urgency_avg": row[6],
        "ai_summary": row[7] or "",
        "ai_themes": json.loads(row[8]) if row[8] else [],
        "bullish_sectors": json.loads(row[9]) if row[9] else [],
        "bearish_sectors": json.loads(row[10]) if row[10] else [],
        "agent_score": row[11],
        "generated_at": row[12],
        "computed_by": row[13],
    }


# ── 公开 API ─────────────────────────────────────────────
async def get_period_insight(period: str, force_regenerate: bool = False,
                             max_cache_age_secs: int = 6 * 3600) -> dict:
    """
    公开 API：读缓存或生成（带历史 context）
    - 默认 6h 内的缓存直接返回
    - force_regenerate=True 强制重新生成（即使有缓存）
    """
    if period not in PERIODS:
        return {"ok": False, "error": f"invalid_period: {period}"}

    if not force_regenerate:
        cached = await _read_period_insight(period)
        if cached:
            age = int(time.time()) - cached["generated_at"]
            if age < max_cache_age_secs:
                cached["ok"] = True
                cached["from_cache"] = True
                cached["cache_age_secs"] = age
                return cached

    lookback_secs = PERIODS[period]["lookback_secs"]
    now = int(time.time())
    period_end = now
    period_start = now - lookback_secs

    gen = await _generate_period_insight(period, period_start, period_end)
    if gen.get("ok"):
        await _save_period_insight(period, period_start, period_end, gen)
        cached = await _read_period_insight(period)
        if cached:
            cached["ok"] = True
            cached["from_cache"] = False
            return cached
    return gen


async def get_all_periods() -> dict:
    """一次返回 4 个周期的数据"""
    out = {"ok": True, "periods": {}}
    for period in PERIODS:
        out["periods"][period] = await get_period_insight(period)
    return out


# ── 历史/对比 API（v2 新增） ──────────────────────────────
async def get_period_history(period: str = None, limit: int = 10) -> dict:
    """读 history 表。period=None 返回所有周期的最近 N 条。

    v3 排序：按 period_end DESC（新闻截止时间倒序）—— 洞察是"过去 N 天新闻"的总结，
    应该按新闻时间线排序，不是按 AI 写的时间。每个 period 都有 period_start~period_end
    表示这条洞察覆盖的新闻时间窗口。
    """
    async with get_db() as db:
        if period:
            cur = await db.execute(
                """SELECT id, period, period_start, period_end, news_count,
                          ai_summary, generated_at, references_prior_id,
                          new_themes, continued_themes, resolved_themes, trend
                   FROM period_insights_history
                   WHERE period = ?
                   ORDER BY period_end DESC LIMIT ?""",
                (period, limit)
            )
        else:
            cur = await db.execute(
                """SELECT id, period, period_start, period_end, news_count,
                          ai_summary, generated_at, references_prior_id,
                          new_themes, continued_themes, resolved_themes, trend
                   FROM period_insights_history
                   ORDER BY period_end DESC LIMIT ?""",
                (limit,)
            )
        rows = await cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "period": r[1],
            "period_start": r[2],
            "period_end": r[3],
            "news_count": r[4],
            "summary": r[5] or "",
            "generated_at": r[6],
            "references_prior_id": r[7],
            "new_themes": json.loads(r[8]) if r[8] else [],
            "continued_themes": json.loads(r[9]) if r[9] else [],
            "resolved_themes": json.loads(r[10]) if r[10] else [],
            "trend": r[11] or "stable",
        })
    return {"ok": True, "history": out, "count": len(out)}


async def get_period_compare(period: str) -> dict:
    """对比最新 vs 上一期（连续性 diff）"""
    if period not in PERIODS:
        return {"ok": False, "error": f"invalid_period: {period}"}

    history = await get_period_history(period, limit=2)
    items = history["history"]
    if len(items) < 1:
        return {"ok": False, "error": "no_history"}
    if len(items) < 2:
        return {"ok": True, "current": items[0], "prior": None,
                "deltas": {"note": "只有 1 条历史，无法对比"}}

    current, prior = items[0], items[1]

    # 计算 diff
    new_set = set(current["new_themes"])
    continued_set = set(current["continued_themes"])
    resolved_set = set(current["resolved_themes"])
    prior_titles = set()  # 上一期所有 theme titles
    # 从 prior full row 拉完整 themes（重新查）
    async with get_db() as db:
        cur = await db.execute(
            "SELECT ai_themes FROM period_insights_history WHERE id = ?",
            (prior["id"],)
        )
        row = await cur.fetchone()
    if row and row[0]:
        for t in json.loads(row[0]):
            prior_titles.add(t.get("title", ""))

    return {
        "ok": True,
        "current": current,
        "prior": prior,
        "deltas": {
            "new_count": len(current["new_themes"]),
            "continued_count": len(current["continued_themes"]),
            "resolved_count": len(current["resolved_themes"]),
            "trend_change": f"{prior.get('trend', '?')} → {current.get('trend', '?')}",
            "news_count_delta": current["news_count"] - prior["news_count"],
            "age_secs": current["generated_at"] - prior["generated_at"],
        },
    }


# ── 入口 ────────────────────────────────────────────────
async def _run_all():
    """跑全部 4 个周期（用于 cron / 手动触发）"""
    results = {}
    for period in PERIODS:
        print(f"[PeriodInsights] 生成 {period} ...")
        results[period] = await get_period_insight(period, force_regenerate=True)
        if results[period].get("ok"):
            n = results[period].get("news_count", 0)
            print(f"[PeriodInsights] {period} OK ({n} 条新闻)")
        else:
            err = results[period].get("error", "unknown")
            print(f"[PeriodInsights] {period} FAIL: {err}")
    return results


if __name__ == "__main__":
    asyncio.run(_run_all())
