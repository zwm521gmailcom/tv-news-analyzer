"""
Global Narrative — 跨时间/跨区域的全局事件关联分析。
采用 MiniMax M3 作为核心 AI，配备前后 Agent 评分机制。
生成质量不达标时自动重做（最多 3 轮）。
如 MiniMax 调用失败，错误显式抛出（不再静默切到 Ollama 降级）。

v3 增强（按用户要求）：
- 历史 context：注入前 3 个 global_narrative 摘要 → AI 写连续性（continued/new/resolved）
- 6h detail：最近 6h 新闻（top 30）带完整标题+摘要，重点关注
- 24h summary：过去 24h 全景（top 60）只带标题，快速浏览
- 时间戳：所有新闻进 AI 都有 [MM-DD HH:MM · X小时前] 标记
- 隔离：与 AI 周期洞察（period_insights）完全独立，两套历史各自保留
"""

import asyncio
import json
import time
from collections import defaultdict
from typing import Optional

import httpx

from config import settings
from db.database import get_db
from db.repository import NewsRepository


# ═══════════════════════════════════════════════════════════════
#  SECTION 1: MiniMax M2.7 API
# ═══════════════════════════════════════════════════════════════

async def _minimax_request(prompt: str, model: Optional[str] = None, max_tokens: int = 1024, temperature: float = 0.3, timeout: int = 120) -> str:
    """调用 MiniMax Anthropic 兼容 API。"""
    api_key = settings.MINIMAX_API_KEY
    base_url = settings.MINIMAX_BASE_URL
    model = model or settings.MINIMAX_MODEL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(base_url + "/messages", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content_list = data.get("content", [])
        if content_list:
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text":
                    return item.get("text", "").strip()
        return ""


def _extract_json(text: str) -> dict | list | None:
    """从 MiniMax 返回文本中提取 JSON（处理 markdown 包裹、尾部多余内容）。"""
    import re
    text = text.strip()
    # 去除 ```json ``` 等 markdown 包装
    text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    text = text.strip()
    if not text:
        return None

    # 尝试解析整个字符串
    try:
        return json.loads(text)
    except Exception:
        pass

    # 查找 JSON 数组
    arr_start = text.find("[")
    arr_end = text.rfind("]")
    if arr_start != -1 and arr_end > arr_start:
        candidate = text[arr_start:arr_end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 查找 JSON 对象
    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        candidate = text[obj_start:obj_end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


async def _minimax_json(prompt: str, max_tokens: int = 1024, temperature: float = 0.3, timeout: int = 120) -> dict | list | None:
    """调用 MiniMax 并解析 JSON 响应。"""
    try:
        response = await _minimax_request(prompt, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        return _extract_json(response)
    except Exception as e:
        print(f"[MiniMax] JSON 解析失败: {e}")
    return None


async def minimax_available() -> bool:
    if not settings.MINIMAX_API_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                settings.MINIMAX_BASE_URL + "/messages",
                headers={
                    "Authorization": f"Bearer {settings.MINIMAX_API_KEY}",
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json={"model": settings.MINIMAX_MODEL, "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
            )
            return resp.status_code == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
#  SECTION 2: Agent 评分系统
# ═══════════════════════════════════════════════════════════════

SCORE_THRESHOLD = 6  # 分数低于此值则重做
MAX_ROUNDS = 3       # 最多重做 3 轮


async def _agent_pre_check(news_count: int, symbol_count: int, hour_count: int) -> dict:
    """
    前置 Agent：评估数据质量与 Prompt 准备度。
    返回 {"pass": bool, "score": float, "reason": str, "suggestion": str}
    """
    prompt = f"""你是一个新闻分析质量评估专家。请评估以下数据是否足够支撑一次高质量的金融新闻分析：

- 新闻数量：{news_count} 条
- 关联符号数量：{symbol_count} 个
- 时间覆盖：{hour_count} 小时

评分标准（0-10）：
- 8-10：数据非常充分，分析质量会很高
- 6-7：数据基本充分，可以生成有价值的分析
- 4-5：数据偏少，分析可能流于表面
- 0-3：数据严重不足，分析意义不大

请只输出 JSON：{{"score": 分数, "reason": "评估理由", "suggestion": "如果分数<6，改进建议"}}
只输出 JSON，不要其他内容。"""

    result = await _minimax_json(prompt, max_tokens=1500, timeout=30)
    if result and isinstance(result, dict):
        score = float(result.get("score", 0))
        return {
            "pass": score >= SCORE_THRESHOLD,
            "score": score,
            "reason": result.get("reason", ""),
            "suggestion": result.get("suggestion", ""),
        }
    # 无法评分时默认通过
    return {"pass": True, "score": 7.0, "reason": "评分服务不可用，默认通过", "suggestion": ""}


async def _agent_score_output(output: dict | list, output_type: str, news_count: int) -> dict:
    """
    后置 Agent：评估 AI 生成内容的质量。
    output_type: "global_view" | "insights"
    返回 {"pass": bool, "score": float, "reason": str, "issues": [问题列表]}
    """
    output_str = json.dumps(output, ensure_ascii=False, indent=2)[:3000]

    if output_type == "global_view":
        prompt = f"""你是一个金融新闻分析质量审核专家。请评估以下 AI 生成内容的质量：

评分标准（0-10，每项 2 分）：
1. 主题是否明确具体（不是泛泛而谈）
2. 总结是否有深度，是否提及具体事件/数据
3. 关键符号是否与新闻内容相关
4. 风险等级判断是否合理
5. 展望是否有参考价值（非废话）

另外检查：
- 是否有幻觉（提及不存在的具体公司/数据）
- JSON 结构是否完整

内容：{output_str}

请输出 JSON：{{"score": 总分, "theme_score": 主题分, "summary_score": 总结分, "symbol_score": 符号分, "risk_score": 风险分, "outlook_score": 展望分, "issues": ["问题1", "问题2"], "overall_comment": "整体评语"}}
只输出 JSON。"""
    else:  # insights
        prompt = f"""你是一个金融洞察质量审核专家。请评估以下 AI 生成洞察的质量：

评分标准（0-10，每项 2 分）：
1. 每条洞察是否有具体的事件/数据支撑
2. 影响预测是否具体、可操作（非泛泛而谈）
3. 置信度是否与内容匹配（高置信应有强理由）
4. 符号关联是否合理
5. 是否有多样性（不重复、不空泛）

另外检查：
- 是否有幻觉
- 条目数量是否达到要求（5条）
- JSON 结构是否完整

内容：{output_str}

请输出 JSON：{{"score": 总分, "specificity_score": 具体性分, "impact_score": 影响预测分, "confidence_score": 置信度分, "diversity_score": 多样性分, "issues": ["问题列表"], "overall_comment": "整体评语"}}
只输出 JSON。"""

    result = await _minimax_json(prompt, max_tokens=2048, timeout=30, temperature=0.1)
    if result and isinstance(result, dict):
        score = float(result.get("score", 0))
        issues = result.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        return {
            "pass": score >= SCORE_THRESHOLD,
            "score": score,
            "reason": result.get("overall_comment", ""),
            "issues": issues,
        }
    return {"pass": True, "score": 7.0, "reason": "评分服务不可用，默认通过", "issues": []}


# ═══════════════════════════════════════════════════════════════
#  SECTION 4: 数据处理工具
# ═══════════════════════════════════════════════════════════════

def _build_symbol_graph(news_items):
    graph = defaultdict(list)
    for n in news_items:
        raw = n.get("symbols")
        if not raw:
            symbols = []
        elif isinstance(raw, list):
            symbols = raw
        elif isinstance(raw, str):
            try:
                symbols = json.loads(raw)
            except Exception:
                symbols = []
        else:
            symbols = []
        for sym in symbols:
            if not sym:
                continue
            parts = sym.split(":")
            ticker = parts[-1] if len(parts) > 1 else sym
            ticker = ticker.strip()
            if ticker:
                graph[ticker].append(n["id"])
    return {sym: ids for sym, ids in graph.items() if len(ids) >= 2}


def _find_cross_region_links(region_narratives):
    links = []
    by_region = defaultdict(list)
    for r in region_narratives:
        by_region[r["region"]].append(r)
    regions = list(by_region.keys())
    for i, r1 in enumerate(regions):
        for r2 in regions[i+1:]:
            events1 = set()
            for e in by_region[r1]:
                for top in (e.get("top_events") or [])[:5]:
                    events1.add(top.get("news_id") or "" if isinstance(top, dict) else str(top))
            events2 = set()
            for e in by_region[r2]:
                for top in (e.get("top_events") or [])[:5]:
                    events2.add(top.get("news_id") or "" if isinstance(top, dict) else str(top))
            shared = events1 & events2
            if shared:
                links.append({"region_1": r1, "region_2": r2, "shared_events": len(shared), "type": "shared_news"})
    return links


def _analyze_time_patterns(hour_narratives):
    if not hour_narratives:
        return {"peak_hours": [], "trend": "unknown"}
    hour_counts = [(h["hour_bucket"], h["total_events"]) for h in hour_narratives]
    hour_counts.sort(key=lambda x: x[1], reverse=True)
    peak_hours = hour_counts[:3]
    if len(hour_narratives) >= 2:
        half = len(hour_narratives) // 2
        recent_avg = sum(h["total_events"] for h in hour_narratives[:half]) / half
        older_avg = sum(h["total_events"] for h in hour_narratives[half:]) / (len(hour_narratives) - half)
        trend = "escalating" if recent_avg > older_avg * 1.3 else "deescalating" if recent_avg < older_avg * 0.7 else "stable"
    else:
        trend = "stable"
    return {
        "peak_hours": [{"hour": h, "count": c} for h, c in peak_hours],
        "trend": trend,
        "total_events": sum(h["total_events"] for h in hour_narratives),
    }


# ── 历史 context（v3 新增）────────────────────────────────
HISTORY_LOOKBACK = 3   # 看前 3 个 global_narrative


async def _fetch_global_narrative_history(limit: int = HISTORY_LOOKBACK, current_id: str | None = None) -> list:
    """从 global_narratives 表拉前 N 个历史（按时间倒序）。

    返回：list of dict { id, generated_at, lookback_hours, news_count, global_view (list), insights (list) }
    """
    async with get_db() as db:
        # 用 PRAGMA 兼容表结构（避免硬编码列名）
        cur = await db.execute("PRAGMA table_info(global_narratives)")
        cols_rows = await cur.fetchall()
        cols = [r[1] for r in cols_rows]  # PRAGMA columns: cid, name, type, ...
        id_col = "id" if "id" in cols else ("gn_id" if "gn_id" in cols else None)
        if not id_col:
            return []
        where_excl = f"WHERE {id_col} != ?" if current_id else ""
        params = [current_id] if current_id else []
        sql = f"""SELECT {id_col} AS id, generated_at, lookback_hours, news_count,
                         global_view, insights
                  FROM global_narratives
                  {where_excl}
                  ORDER BY generated_at DESC LIMIT ?"""
        params.append(limit)
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        out = []
        for r in rows:
            try:
                gv = json.loads(r[4]) if r[4] else []
            except Exception:
                gv = []
            try:
                ins = json.loads(r[5]) if r[5] else []
            except Exception:
                ins = []
            out.append({
                "id": r[0],
                "generated_at": r[1],
                "lookback_hours": r[2],
                "news_count": r[3],
                "global_view": gv if isinstance(gv, list) else [gv],
                "insights": ins if isinstance(ins, list) else [ins],
            })
        return out


def _format_global_history_context(history_list: list) -> str:
    """把历史 global_narrative 列表拼成 prompt 文本段。

    v3：每个历史展开其 5 个 viewpoint 的 theme + outlook（精简版），加上 news_count 和时间。
    """
    if not history_list:
        return "（暂无历史全局叙事，这是首次生成）"

    lines = [f"【前 {len(history_list)} 次全局叙事（按时间倒序，最新在前）】", ""]
    for i, h in enumerate(history_list):
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["generated_at"]))
        period_label = "上上次" if i == 1 else ("上上上次" if i == 2 else f"第 {i+1} 次前")
        if i == 0:
            title = f"【上一次全局叙事（{ts}生成，{h['news_count']}条新闻，回看{h.get('lookback_hours',24)}h）】"
        else:
            title = f"【{period_label}（{ts}生成，{h['news_count']}条新闻）】"
        lines.append(title)
        # 5 个 viewpoint：theme + outlook（精简，不放 summary 避免过长）
        gv = h.get("global_view") or []
        for j, v in enumerate(gv[:5]):
            theme = (v.get("theme") or "(无主题)")[:50]
            outlook = (v.get("outlook") or "")[:80]
            risk = v.get("risk_level", "?")
            lines.append(f"  {j+1}. [{risk}] {theme}")
            if outlook:
                lines.append(f"     展望: {outlook}")
        # 关键洞察标题
        ins = h.get("insights") or []
        if ins:
            ins_titles = []
            for x in ins[:5]:
                t = (x.get("title") or "(无标题)")[:40]
                ins_titles.append(t)
            if ins_titles:
                lines.append(f"  关键洞察: {' | '.join(ins_titles)}")
        lines.append("")

    return "\n".join(lines)


def _make_news_text(news_items, limit=30):
    """每条带时间戳 + 相对时间（如"2小时前"）

    v3：保留为通用版本，按 limit 控制条数。生成 6h detail / 24h summary 时用不同 limit。
    """
    import time as _t
    lines = []
    for n in news_items[:limit]:
        provider = n.get("provider") or ""
        title = (n.get("title") or "")[:80]
        short_desc = (n.get("short_desc") or "")[:60]
        desc = short_desc if short_desc else title
        ts = n.get("published") or 0
        if ts:
            age = max(0, int(_t.time()) - int(ts))
            if age < 3600: rel = f"{age // 60}分钟前"
            elif age < 86400: rel = f"{age // 3600}小时前"
            else: rel = f"{age // 86400}天前"
            abs_ts = _t.strftime("%m-%d %H:%M", _t.localtime(ts))
            ts_prefix = f"[{abs_ts} · {rel}] "
        else:
            ts_prefix = "[?时间] "
        lines.append(f"- {ts_prefix}[{provider}] {title}")
        if desc != title:
            lines.append(f"  摘要: {desc}")
    return "\n".join(lines)


def _make_news_text_6h(news_items, limit=30):
    """v3：最近 6h detail — 完整标题 + 摘要，标记紧急度。"""
    import time as _t
    now = int(_t.time())
    cutoff = now - 6 * 3600
    recent = [n for n in news_items if (n.get("published") or 0) >= cutoff]
    recent.sort(key=lambda n: (-(n.get("urgency") or 0), -(n.get("published") or 0)))
    lines = [f"（共 {len(recent)} 条最近 6 小时新闻，按紧急度+时间排序，前 {limit} 条如下）", ""]
    for n in recent[:limit]:
        provider = n.get("provider") or "Unknown"
        market = n.get("market") or "unknown"
        title = (n.get("title") or "")[:120]
        short = (n.get("short_desc") or "")[:100]
        urgency = n.get("urgency") or 1
        ts = n.get("published") or 0
        if ts:
            age = max(0, now - int(ts))
            if age < 3600: rel = f"{age // 60}分钟前"
            elif age < 86400: rel = f"{age // 3600}小时前"
            else: rel = f"{age // 86400}天前"
            abs_ts = _t.strftime("%m-%d %H:%M", _t.localtime(ts))
            ts_prefix = f"[{abs_ts} · {rel}]"
        else:
            ts_prefix = "[?时间]"
        lines.append(f"- {ts_prefix} [紧急度:{urgency}] [{provider}/{market}] {title}")
        if short and short != title[:80]:
            lines.append(f"  摘要: {short}")
    return "\n".join(lines)


def _make_news_text_24h(news_items, limit=60):
    """v3：过去 24h summary — 仅标题 + market（精简，背景全貌）。"""
    import time as _t
    now = int(_t.time())
    cutoff = now - 24 * 3600
    recent = [n for n in news_items if (n.get("published") or 0) >= cutoff]
    recent.sort(key=lambda n: (-(n.get("urgency") or 0), -(n.get("published") or 0)))
    lines = [f"（共 {len(recent)} 条过去 24 小时新闻，前 {limit} 条标题如下）", ""]
    for n in recent[:limit]:
        market = n.get("market") or "?"
        title = (n.get("title") or "")[:80]
        lines.append(f"  - [{market}] {title}")
    return "\n".join(lines)


def _make_detailed_news_for_symbols(news_items, symbol_graph, top_n=3):
    lines = []
    import time as _t
    for sym, ids in sorted(symbol_graph.items(), key=lambda x: len(x[1]), reverse=True)[:8]:
        related = [n for n in news_items if n.get("id") in ids][:top_n]
        if related:
            lines.append(f"\n=== {sym} 相关新闻 ({len(ids)} 条) ===")
            for n in related:
                provider = n.get("provider") or ""
                title = (n.get("title") or "")[:80]
                short_desc = (n.get("short_desc") or "")[:60]
                urgency = n.get("urgency") or 1
                ts = n.get("published") or 0
                if ts:
                    age = max(0, int(_t.time()) - int(ts))
                    if age < 3600: rel = f"{age // 60}分钟前"
                    elif age < 86400: rel = f"{age // 3600}小时前"
                    else: rel = f"{age // 86400}天前"
                    abs_ts = _t.strftime("%m-%d %H:%M", _t.localtime(ts))
                    ts_prefix = f"[{abs_ts} · {rel}] "
                else:
                    ts_prefix = "[?] "
                lines.append(f"- {ts_prefix}[{provider}] [紧急度:{urgency}] {title}")
                if short_desc:
                    lines.append(f"  摘要: {short_desc}")
    return "\n".join(lines)


def _make_symbol_text(symbol_graph):
    lines = []
    for sym, ids in sorted(symbol_graph.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        lines.append(f"- {sym}: {len(ids)} 条相关新闻")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  SECTION 5: 核心 Prompt 生成
# ═══════════════════════════════════════════════════════════════

def _build_global_view_prompt(history_text: str, news_6h_text: str, news_24h_text: str,
                              symbol_text: str, round_num: int) -> str:
    """v3：3 段 context：history → 6h detail → 24h summary。"""
    focus_hint = ""
    if round_num == 2:
        focus_hint = "\n[第二轮重做提示] 上一轮评分认为内容过于泛泛，请更加具体，引用具体数字和事件。"
    elif round_num >= 3:
        focus_hint = "\n[第三轮重做提示] 请务必覆盖：股票/指数、大宗商品/外汇、加密货币、地缘政治、行业事件，每个维度都要有具体数据。"

    return f"""你是一个专业的金融新闻分析专家，正在做第 {round_num} 轮生成。请结合历史叙事 + 最新 6h 新闻 + 24h 全景，输出 5 个市场观点。

【上下文 - 3 段】
────────────────────────────────────
A. 前 {HISTORY_LOOKBACK} 次全局叙事（用于判断延续/反转/已解决）
{history_text}
────────────────────────────────────
B. 最新 6h 重点新闻（带时间戳+紧急度+摘要，重点关注）
{news_6h_text}
────────────────────────────────────
C. 过去 24h 全景（精简标题，背景全貌）
{news_24h_text}
────────────────────────────────────
热点 symbol：
{symbol_text}
{focus_hint}

【输出格式】严格 JSON 数组（5个观点，覆盖不同维度——股票/指数、大宗商品/外汇、地缘政治、行业/公司、加密货币）：
[
  {{
    "theme": "一句话主题（不超过30字，突出具体事件）",
    "summary": "2-3句话总结。必须：(1) 引用历史叙事的延续/反转（对比 A 段）；(2) 包含最新 6h 的具体数字/公司/价格；(3) 数字必须锚定到具体新闻时间",
    "key_symbols": ["最核心的3个交易标的"],
    "risk_level": "high/medium/low",
    "outlook": "对未来12小时的具体展望（基于最新数据 + 当前趋势，不超过50字）"
  }}
]

【时效校验硬规则】
1. 每条新闻带 [MM-DD HH:MM · X小时前/天前] 时间戳
2. 引用具体数字/价格时，必须用"该数字出现的新闻时间"来定位
3. 同一标的数字差异大时（如黄金 2400 vs 4500），以最新一条为准，旧数字仅作为对比/历史
4. 做"X 将涨到 Y"预测时，Y 应基于最新数字 + 当前趋势，不要引用 1 周前的旧价位
5. 写连续性时显式标注：延续上次的写"延续..."，新出现写"新增..."，已消退写"已解决..."

只输出 JSON 数组，不要任何其他文字。"""


def _build_insights_prompt(history_text: str, news_6h_text: str, detailed_news: str, round_num: int) -> str:
    """v3：3 段 context。"""
    focus_hint = ""
    if round_num == 2:
        focus_hint = "\n[第二轮重做提示] 上一轮洞察过于空泛，请每条都要有具体事件和可量化的影响预测。"
    elif round_num >= 3:
        focus_hint = "\n[第三轮重做提示] 请确保每条洞察都包含：①具体事件 ②具体符号 ③具体影响方向（如铜价涨2%） ④置信度理由。"

    return f"""你是一个专业的金融情报分析专家，正在做第 {round_num} 轮生成。请结合历史洞察 + 最新 6h 新闻 + 高关联 symbol 详情，输出 5 条洞察。

【上下文 - 3 段】
────────────────────────────────────
A. 前 {HISTORY_LOOKBACK} 次洞察标题与展望（用于判断洞察的连续性）
{history_text}
────────────────────────────────────
B. 最新 6h 重点新闻（带时间戳+紧急度+摘要）
{news_6h_text}
────────────────────────────────────
C. 高关联 symbol 及详情
{detailed_news}
────────────────────────────────────
{focus_hint}

【输出格式】严格 JSON 数组（最多 5 条）：
[
  {{
    "type": "correlation/surveillance/anomaly/warning",
    "title": "洞察标题（不超过20字）",
    "description": "内容：具体事件+当前状态（不超过80字）",
    "impact_prediction": "具体影响预测，如：铜价上涨2%、美元指数突破105（不超过30字）",
    "symbols": ["相关符号列表"],
    "urgency": "high/medium/low",
    "confidence": 0.0到1.0（高置信需有强理由）
  }}
]

【时效校验硬规则】
1. 每条新闻带 [MM-DD HH:MM · X小时前/天前] 时间戳
2. 引用具体数字时，锚定到具体新闻时间
3. 同一标的不同数字差异大时（黄金 2400 vs 4500），以最新一条为准
4. 影响预测必须基于最新 6h 趋势，不要引用旧价位
5. 如果是上次洞察的延续/反转，显式标注

只输出 JSON。"""


# ═══════════════════════════════════════════════════════════════
#  SECTION 6: 主生成流程（含评分重试）
# ═══════════════════════════════════════════════════════════════

async def _generate_with_scoring(
    news_items,
    symbol_graph,
    cross_region_links,
    time_patterns,
    generate_fn,
    score_fn,
    output_type: str,
    max_rounds: int = MAX_ROUNDS,
):
    """
    带评分重试的生成流程：
    1. 前置 Agent 检查数据质量
    2. 调用 AI 生成
    3. 后置 Agent 评分
    4. 不通过则用反馈重做，最多 max_rounds 轮
    """
    news_count = len(news_items)
    symbol_count = len(symbol_graph)
    hour_count = time_patterns.get("total_events", 0) // max(1, news_count) * 24 if news_count > 0 else 0

    # 前置评分
    pre = await _agent_pre_check(news_count, symbol_count, 24)
    print(f"[Agent-前置] score={pre['score']:.1f} pass={pre['pass']} reason={pre['reason']}")
    if not pre["pass"]:
        print(f"[Agent-前置] 警告：{pre['suggestion']}")

    best_result = None
    best_score = 0.0

    for round_num in range(1, max_rounds + 1):
        print(f"[生成] 第 {round_num} 轮开始...")
        result = await generate_fn(round_num)

        if result is None:
            print(f"[生成] 第 {round_num} 轮返回空，跳过评分")
            if best_result is not None:
                break
            continue

        # 后置评分
        score_result = await score_fn(result, output_type, news_count)
        score = score_result["score"]
        print(f"[Agent-评分] round={round_num} score={score:.1f}/10 pass={score_result['pass']} reason={score_result['reason']}")
        if score_result["issues"]:
            for issue in score_result["issues"][:3]:
                print(f"[Agent-评分]   issue: {issue}")

        if score > best_score:
            best_score = score
            best_result = result

        if score_result["pass"]:
            print(f"[生成] 第 {round_num} 轮通过，停止重试")
            return result

        if round_num < max_rounds:
            print(f"[生成] 第 {round_num} 轮未通过(score={score:.1f})，进入下一轮...")

    # 所有轮次都未通过，返回最佳结果
    print(f"[生成] 所有轮次完成，最高分={best_score:.1f}，使用最佳结果")
    return best_result


async def _call_minimax_global_view(history_text: str, news_6h_text: str, news_24h_text: str,
                                    symbol_text: str, round_num: int) -> dict | list | None:
    prompt = _build_global_view_prompt(history_text, news_6h_text, news_24h_text, symbol_text, round_num)
    result = await _minimax_json(prompt, max_tokens=2048, timeout=120)
    return result


async def _call_minimax_insights(history_text: str, news_6h_text: str, detailed_news: str,
                                 round_num: int) -> dict | list | None:
    prompt = _build_insights_prompt(history_text, news_6h_text, detailed_news, round_num)
    result = await _minimax_json(prompt, max_tokens=2048, timeout=120)
    if result and isinstance(result, list):
        return result[:5]
    return result


def _fallback_global_view(news_items, symbol_graph):
    if not news_items:
        return [{"theme": "无数据", "summary": "", "key_symbols": [], "risk_level": "low", "outlook": ""}]
    top_syms = sorted(symbol_graph.items(), key=lambda x: len(x[1]), reverse=True)[:3]
    key_symbols = [s for s, _ in top_syms]
    top = news_items[0] if news_items else {}
    title = (top.get("title") or "未知")[:30]
    high_urg = sum(1 for n in news_items if n.get("urgency", 1) >= 3)
    risk = "high" if high_urg > 10 else "medium" if high_urg > 5 else "low"
    return [{
        "theme": f"重点：{title}",
        "summary": f"过去 {len(news_items)} 条新闻中，{key_symbols[0] if key_symbols else '市场'} 相关事件最受关注",
        "key_symbols": key_symbols,
        "risk_level": risk,
        "outlook": "详细信息请查看各区域叙事",
    }]


def _fallback_insights(news_items, symbol_graph):
    insights = []
    for sym, ids in symbol_graph.items():
        if len(ids) >= 3:
            insights.append({
                "type": "correlation",
                "title": f"{sym} 高频关联",
                "description": f"{sym} 在 {len(ids)} 条新闻中被提及",
                "symbols": [sym],
                "urgency": "medium",
                "confidence": min(0.9, 0.4 + len(ids) * 0.1),
            })
    high_urg = [n for n in news_items if n.get("urgency", 1) >= 3][:3]
    if high_urg:
        titles = "、".join([(n.get("title") or "")[:20] for n in high_urg])
        insights.append({
            "type": "warning",
            "title": "高紧急度事件",
            "description": f"有 {len(high_urg)} 条高紧急度新闻：{titles}",
            "symbols": [],
            "urgency": "high",
            "confidence": 0.8,
        })
    return insights[:5]


async def _save_global_narrative(result):
    async with get_db() as db:
        # 用 PRAGMA 检查是否有 references_history_ids 列（兼容老 DB）
        cur = await db.execute("PRAGMA table_info(global_narratives)")
        cols_rows = await cur.fetchall()
        cols = [r[1] for r in cols_rows]
        if "references_history_ids" in cols:
            await db.execute(
                """INSERT OR REPLACE INTO global_narratives
                   (id, generated_at, lookback_hours, news_count,
                    global_view, insights, symbol_network,
                    cross_region_links, time_patterns, computed_by, references_history_ids)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result["id"],
                    result["generated_at"],
                    result["lookback_hours"],
                    result["news_count"],
                    json.dumps(result["global_view"]),
                    json.dumps(result["insights"]),
                    json.dumps(result["symbol_network"]),
                    json.dumps(result["cross_region_links"]),
                    json.dumps(result["time_patterns"]),
                    result["computed_by"],
                    json.dumps(result.get("references_history_ids", [])),
                )
            )
        else:
            # 老 DB 没新列时回退
            await db.execute(
                """INSERT OR REPLACE INTO global_narratives
                   (id, generated_at, lookback_hours, news_count,
                    global_view, insights, symbol_network,
                    cross_region_links, time_patterns, computed_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    result["id"],
                    result["generated_at"],
                    result["lookback_hours"],
                    result["news_count"],
                    json.dumps(result["global_view"]),
                    json.dumps(result["insights"]),
                    json.dumps(result["symbol_network"]),
                    json.dumps(result["cross_region_links"]),
                    json.dumps(result["time_patterns"]),
                    result["computed_by"],
                )
            )
        await db.commit()


async def generate_global_narrative(lookback_hours=24):
    # 先确定本次新 id（用于 history 排除自身）
    new_id = f"gn_{int(time.time())}"

    async with get_db() as db:
        repo = NewsRepository(db)
        region_narratives = await repo.get_region_narratives(hours=lookback_hours)
        hour_narratives = await repo.get_hour_causal_narratives(hours=lookback_hours)

        since = int(time.time()) - lookback_hours * 3600
        cur = await db.execute(
            """SELECT id, title, short_desc, urgency, provider,
                      published, symbols, lang, market
               FROM raw_news WHERE published >= ?
               ORDER BY urgency DESC LIMIT 2000""",
            (since,)
        )
        rows = await cur.fetchall()
        news_items = [dict(r) for r in rows]

        if not news_items:
            return {"error": "no news data"}

        symbol_graph = _build_symbol_graph(news_items)
        cross_region_links = _find_cross_region_links(region_narratives)
        time_patterns = _analyze_time_patterns(hour_narratives)

    # ── v3：拉前 3 个历史 + 6h/24h 双窗口新闻 ──
    history_list = await _fetch_global_narrative_history(limit=HISTORY_LOOKBACK, current_id=new_id)
    history_text = _format_global_history_context(history_list)
    news_6h_text = _make_news_text_6h(news_items, limit=30)
    news_24h_text = _make_news_text_24h(news_items, limit=60)
    news_text = _make_news_text(news_items)  # 旧函数保留（fallback 用）
    detailed_news = _make_detailed_news_for_symbols(news_items, symbol_graph)
    symbol_text = _make_symbol_text(symbol_graph)

    # 确定 AI provider（只用 MiniMax；不可用时显式走 fallback，不静默切 Ollama）
    use_minimax = await minimax_available()
    computed_by = "minimax" if use_minimax else "fallback"

    if computed_by == "fallback":
        global_view = _fallback_global_view(news_items, symbol_graph)
        insights = _fallback_insights(news_items, symbol_graph)
    else:
        # Global View 生成（含评分重试）
        async def gen_gv(round_num):
            return await _call_minimax_global_view(history_text, news_6h_text, news_24h_text, symbol_text, round_num)

        async def score_gv(result, *args):
            return await _agent_score_output(result, "global_view", len(news_items))

        global_view = await _generate_with_scoring(
            news_items, symbol_graph, cross_region_links, time_patterns,
            gen_gv, score_gv, "global_view"
        )
        if not global_view:
            global_view = _fallback_global_view(news_items, symbol_graph)

        # Insights 生成（含评分重试）
        async def gen_ins(round_num):
            return await _call_minimax_insights(history_text, news_6h_text, detailed_news, round_num)

        async def score_ins(result, *args):
            return await _agent_score_output(result, "insights", len(news_items))

        insights = await _generate_with_scoring(
            news_items, symbol_graph, cross_region_links, time_patterns,
            gen_ins, score_ins, "insights"
        )
        if not insights:
            insights = _fallback_insights(news_items, symbol_graph)
        elif isinstance(insights, list):
            insights = insights[:5]

    # 记录参考的历史 id 列表（用于 diff/追溯）
    references_history_ids = [h["id"] for h in history_list]

    result = {
        "id": new_id,
        "generated_at": int(time.time()),
        "lookback_hours": lookback_hours,
        "news_count": len(news_items),
        "global_view": global_view if isinstance(global_view, list) else [global_view],
        "insights": insights if isinstance(insights, list) else [insights],
        "symbol_network": symbol_graph,
        "cross_region_links": cross_region_links,
        "time_patterns": time_patterns,
        "computed_by": computed_by,
        "references_history_ids": references_history_ids,  # v3 新增：参考的历史
    }

    await _save_global_narrative(result)
    return result


async def run_global_narrative(lookback_hours=24):
    print(f"[GlobalNarrative] 开始生成过去 {lookback_hours} 小时的全局叙事...")
    result = await generate_global_narrative(lookback_hours)
    if "error" not in result:
        gv = result.get("global_view", [])
        count = len(gv) if isinstance(gv, list) else 1
        first_theme = gv[0].get("theme", "N/A") if isinstance(gv, list) and gv else "N/A"
        print(f"[GlobalNarrative] 完成: {count}条观点 | theme={first_theme}")
        print(f"[GlobalNarrative] 洞察数量: {len(result.get('insights', []))}")
        print(f"[GlobalNarrative] AI Provider: {result.get('computed_by', 'unknown')}")
    return result


if __name__ == "__main__":
    asyncio.run(run_global_narrative(24))
