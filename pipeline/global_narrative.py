"""
Global Narrative — 跨时间/跨区域的全局事件关联分析。
采用 MiniMax M2.7 作为核心 AI，配备前后 Agent 评分机制。
生成质量不达标时自动重做（最多 3 轮）。
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


OLLAMA_BASE = "http://localhost:11434/api"


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
#  SECTION 2: Ollama 降级备用
# ═══════════════════════════════════════════════════════════════

async def ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def ollama_chat(model: str, prompt: str, timeout: int = 120) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.3, "num_predict": 768}},
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


async def get_ollama_json(model: str, prompt: str, timeout: int = 120) -> dict | None:
    try:
        response = await ollama_chat(model, prompt, timeout)
        arr_start = response.find("[")
        arr_end = response.rfind("]") + 1
        if arr_start != -1 and arr_end > arr_start:
            candidate = response[arr_start:arr_end]
            if candidate.count("{") >= 1:
                try:
                    return json.loads(candidate)
                except Exception:
                    pass
        obj_start = response.find("{")
        obj_end = response.rfind("}") + 1
        if obj_start != -1 and obj_end > obj_start:
            return json.loads(response[obj_start:obj_end])
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
#  SECTION 3: Agent 评分系统
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


def _make_news_text(news_items, limit=30):
    lines = []
    for n in news_items[:limit]:
        provider = n.get("provider") or ""
        title = (n.get("title") or "")[:80]
        short_desc = (n.get("short_desc") or "")[:60]
        desc = short_desc if short_desc else title
        lines.append(f"- [{provider}] {title}")
        if desc != title:
            lines.append(f"  摘要: {desc}")
    return "\n".join(lines)


def _make_detailed_news_for_symbols(news_items, symbol_graph, top_n=3):
    lines = []
    for sym, ids in sorted(symbol_graph.items(), key=lambda x: len(x[1]), reverse=True)[:8]:
        related = [n for n in news_items if n.get("id") in ids][:top_n]
        if related:
            lines.append(f"\n=== {sym} 相关新闻 ({len(ids)} 条) ===")
            for n in related:
                provider = n.get("provider") or ""
                title = (n.get("title") or "")[:80]
                short_desc = (n.get("short_desc") or "")[:60]
                urgency = n.get("urgency") or 1
                lines.append(f"- [{provider}] [紧急度:{urgency}] {title}")
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

def _build_global_view_prompt(news_text: str, symbol_text: str, round_num: int) -> str:
    focus_hint = ""
    if round_num == 2:
        focus_hint = "\n[第二轮重做提示] 上一轮评分认为内容过于泛泛，请更加具体，引用具体数字和事件。"
    elif round_num >= 3:
        focus_hint = "\n[第三轮重做提示] 请务必覆盖：股票/指数、大宗商品/外汇、加密货币、地缘政治、行业事件，每个维度都要有具体数据。"

    return f"""你是一个专业的金融新闻分析专家。以下是过去 24 小时的重大新闻事件列表。

请分析并输出一个 JSON 数组，包含 5 个市场观点，每个对象包含：
[
  {{
    "theme": "一句话描述该市场主题（不超过30字，突出具体事件）",
    "summary": "用2-3句话总结，包含具体数字、具体公司名、具体价格/涨幅（不说废话）",
    "key_symbols": ["最核心的3个交易标的"],
    "risk_level": "high/medium/low",
    "outlook": "对未来12小时的具体展望（要有预测方向，不超过50字）"
  }}
]

{focus_hint}

要求：5个观点要覆盖不同维度——股票/指数、大宗商品/外汇、地缘政治、行业/公司、加密货币（如数据支持）。只输出 JSON 数组。

新闻列表：
{news_text}

热点 symbol：
{symbol_text}"""


def _build_insights_prompt(news_text: str, detailed_news: str, round_num: int) -> str:
    focus_hint = ""
    if round_num == 2:
        focus_hint = "\n[第二轮重做提示] 上一轮洞察过于空泛，请每条都要有具体事件和可量化的影响预测。"
    elif round_num >= 3:
        focus_hint = "\n[第三轮重做提示] 请确保每条洞察都包含：①具体事件 ②具体符号 ③具体影响方向（如铜价涨2%） ④置信度理由。"

    return f"""你是一个专业的金融情报分析专家。从以下新闻中发现关联线索，并预测影响。

对每条洞察，判断：
1. 发生了什么（要具体）
2. 对市场意味着什么（要有方向）
3. 影响持续多久、强度多大（要可量化）

输出 JSON 数组（5条）：
[
  {{
    "type": "correlation/surveillance/anomaly/warning",
    "title": "洞察标题（不超过20字，突出核心事件）",
    "description": "内容：具体事件+当前状态（不超过80字）",
    "impact_prediction": "具体影响预测，如：铜价上涨2%、美元指数突破105、AMZN股价上涨5%（不超过30字）",
    "symbols": ["相关符号列表"],
    "urgency": "high/medium/low",
    "confidence": 0.0到1.0（高置信需有强理由）
  }}
]

{focus_hint}

最多 5 条。只输出 JSON。

新闻摘要：
{news_text}

高关联 symbol 及详情：
{detailed_news}"""


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


async def _call_minimax_global_view(news_text: str, symbol_text: str, round_num: int) -> dict | list | None:
    prompt = _build_global_view_prompt(news_text, symbol_text, round_num)
    result = await _minimax_json(prompt, max_tokens=1536, timeout=120)
    return result


async def _call_minimax_insights(news_text: str, detailed_news: str, round_num: int) -> dict | list | None:
    prompt = _build_insights_prompt(news_text, detailed_news, round_num)
    result = await _minimax_json(prompt, max_tokens=1536, timeout=120)
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

        news_text = _make_news_text(news_items)
        detailed_news = _make_detailed_news_for_symbols(news_items, symbol_graph)
        symbol_text = _make_symbol_text(symbol_graph)

        # 确定 AI provider
        use_minimax = await minimax_available()
        use_ollama = await ollama_available()
        computed_by = "minimax" if use_minimax else "ollama" if use_ollama else "fallback"

        if computed_by == "fallback":
            global_view = _fallback_global_view(news_items, symbol_graph)
            insights = _fallback_insights(news_items, symbol_graph)
        else:
            # Global View 生成（含评分重试）
            async def gen_gv(round_num):
                if use_minimax:
                    return await _call_minimax_global_view(news_text, symbol_text, round_num)
                else:
                    return await get_ollama_json("qwen2.5:7b",
                        _build_global_view_prompt(news_text, symbol_text, round_num))

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
                if use_minimax:
                    return await _call_minimax_insights(news_text, detailed_news, round_num)
                else:
                    return await get_ollama_json("qwen2.5:7b",
                        _build_insights_prompt(news_text, detailed_news, round_num))

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

        result = {
            "id": f"gn_{int(time.time())}",
            "generated_at": int(time.time()),
            "lookback_hours": lookback_hours,
            "news_count": len(news_items),
            "global_view": global_view if isinstance(global_view, list) else [global_view],
            "insights": insights if isinstance(insights, list) else [insights],
            "symbol_network": symbol_graph,
            "cross_region_links": cross_region_links,
            "time_patterns": time_patterns,
            "computed_by": computed_by,
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
