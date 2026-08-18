"""
AI Narrator — 使用 Ollama qwen2.5:7b 自动生成新闻事件的区域叙事和因果链。

每小时由 Scheduler 触发，或由脚本手动运行。
"""

import asyncio
import json
import time
from collections import defaultdict

import httpx

from db.database import get_db
from db.models import RegionNarrative, HourCausalNarrative
from db.repository import NewsRepository


OLLAMA_BASE = "http://localhost:11434/api"


async def ollama_available() -> bool:
    """检查 Ollama 是否可用"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def ollama_chat(model: str, prompt: str, timeout: int = 60) -> str:
    """调用 Ollama 生成内容"""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 512},
            }
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


# ── 区域中心坐标映射 ─────────────────────────────────────────
REGION_CENTERS = {
    "Middle East":    (29.3, 47.6),
    "Asia":          (35.0, 105.0),
    "North America":  (40.0, -100.0),
    "Europe":         (50.0, 10.0),
    "South America":  (-15.0, -60.0),
    "Other":         (20.0, 0.0),
}


async def generate_region_narratives(hour_bucket: int, lookback_hours: int = 2) -> None:
    """
    按区域分组新闻，调用 Ollama 为每个区域生成一句话叙事。
    """
    async with get_db() as db:
        repo = NewsRepository(db)

        # 聚类: 按 region 分组新闻
        since = hour_bucket - lookback_hours * 3600
        region_groups = await repo.get_geo_events_grouped_by_region(hours=lookback_hours)

        for region, events in region_groups.items():
            if not events:
                continue

            # 计算区域紧急度
            urgency_scores = [e.get("urgency", 1) for e in events]
            avg_urgency = sum(urgency_scores) / len(urgency_scores) if urgency_scores else 1
            urgency_score = min(1.0, avg_urgency / 3.0)

            # 构造新闻列表文本
            news_list_text = "\n".join([
                f"- [{e.get('provider', '')}] {e.get('title', '')[:100]}"
                for e in events[:20]  # 最多20条
            ])

            # 提取 top events（最高紧急度的5条）
            top_events = [
                {
                    "news_id": e.get("id", ""),
                    "title": e.get("title", ""),
                    "urgency": e.get("urgency", 1),
                }
                for e in sorted(events, key=lambda x: x.get("urgency", 0), reverse=True)[:5]
            ]

            # 调用 Ollama 生成叙事
            lat, lng = REGION_CENTERS.get(region, (20.0, 0.0))

            if await ollama_available():
                prompt = f"""你是一个专业的金融新闻分析助手。阅读以下来自「{region}」地区的新闻事件，用一句话描述该地区最重要的事件。

要求：
- 一句话，不超过40字
- 说明发生了什么事及其市场影响
- 标注涉及的关键资产或市场类型
- 用中文输出

新闻列表：
{news_list_text}

只输出事件描述，不要输出其他内容："""

                try:
                    ai_brief = await ollama_chat("qwen2.5:7b", prompt, timeout=30)
                except Exception as e:
                    print(f"[AINarrator] Ollama 调用失败: {e}")
                    ai_brief = _fallback_brief(region, events)
                computed_by = "ollama"
            else:
                ai_brief = _fallback_brief(region, events)
                computed_by = "fallback"

            narrative = RegionNarrative(
                id=f"rn_{hour_bucket}_{region.replace(' ', '_')}",
                hour_bucket=hour_bucket,
                region=region,
                latitude=lat,
                longitude=lng,
                news_count=len(events),
                top_events=top_events,
                ai_brief=ai_brief,
                ai_reasoning=None,
                urgency_score=urgency_score,
                computed_at=int(time.time()),
                computed_by=computed_by,
            )
            await repo.save_region_narrative(narrative)

        print(f"[AINarrator] 区域叙事生成完成: {len(region_groups)} 个区域")


def _fallback_brief(region: str, events: list[dict]) -> str:
    """Ollama 不可用时的降级叙事"""
    if not events:
        return f"{region} 区域无重大事件"

    top = events[0]
    title = top.get("title", "未知事件")[:30]
    provider = top.get("provider", "")
    urgency = top.get("urgency", 1)

    urgency_label = {3: "紧急", 2: "重要", 1: "一般"}.get(urgency, "")
    return f"{urgency_label}：{title}（来源：{provider}）"


async def generate_causal_chain(hour_bucket: int, lookback_hours: int = 3) -> None:
    """
    分析该小时的事件，调用 Ollama 生成因果链叙事。
    """
    async with get_db() as db:
        repo = NewsRepository(db)

        # 获取过去几小时的新闻
        since = hour_bucket - lookback_hours * 3600
        cur = await db.execute(
            """SELECT r.id, r.title, r.short_desc, r.urgency, r.provider,
                      r.published, r.symbols, r.lang, r.market
               FROM raw_news r
               WHERE r.published >= ? AND r.published < ?
               ORDER BY r.urgency DESC""",
            (hour_bucket, hour_bucket + 3600)
        )
        rows = await cur.fetchall()
        news_list = [dict(r) for r in rows]

        if not news_list:
            return

        # 构造新闻摘要
        events_text = "\n".join([
            f"- [{e.get('provider', '')}] {e.get('title', '')[:80]}"
            for e in news_list[:15]
        ])

        total_events = len(news_list)

        if await ollama_available():
            prompt = f"""分析以下金融新闻事件，找出它们之间的逻辑关系，生成因果链叙事。

规则：
- 识别最重要的1-3个核心事件
- 说明每个事件的直接原因和市场影响
- 按因果关系排列（先因后果）
- 输出JSON数组格式：[{{"event": "事件", "cause": "原因", "effect": "影响"}}]
- 每个影响描述不超过30字
- 只输出JSON，不要其他内容

新闻列表：
{events_text}"""

            try:
                response = await ollama_chat("qwen2.5:7b", prompt, timeout=45)
                # 尝试解析 JSON
                chain = _parse_json_chain(response)
                if chain:
                    ai_summary = f"本小时共 {total_events} 条事件，核心：{'；'.join(c['event'][:20] for c in chain[:2])}"
                else:
                    chain = _fallback_chain(news_list)
                    ai_summary = _fallback_summary(news_list)
                computed_by = "ollama"
            except Exception as e:
                print(f"[AINarrator] Ollama 因果链失败: {e}")
                chain = _fallback_chain(news_list)
                ai_summary = _fallback_summary(news_list)
                computed_by = "fallback"
        else:
            chain = _fallback_chain(news_list)
            ai_summary = _fallback_summary(news_list)
            computed_by = "fallback"

        narrative = HourCausalNarrative(
            id=f"hcn_{hour_bucket}",
            hour_bucket=hour_bucket,
            ai_chain=chain,
            ai_summary=ai_summary,
            total_events=total_events,
            computed_at=int(time.time()),
            computed_by=computed_by,
        )
        await repo.save_hour_causal_narrative(narrative)
        print(f"[AINarrator] 因果链生成完成: {len(chain)} 个节点, {total_events} 条事件")


def _parse_json_chain(response: str) -> list[dict]:
    """尝试解析 Ollama 返回的 JSON"""
    try:
        # 尝试找到 JSON 数组
        start = response.find("[")
        end = response.rfind("]") + 1
        if start != -1 and end > start:
            parsed = json.loads(response[start:end])
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
    except Exception:
        pass
    return []


def _fallback_chain(news_list: list[dict]) -> list[dict]:
    """降级因果链：基于共享 symbol 和 urgency"""
    top = news_list[:3]
    chain = []
    for n in top:
        title = n.get("title", "")[:30]
        symbols = n.get("symbols", [])
        sym_str = ", ".join(s.split(":")[-1] for s in symbols[:2]) if symbols else "市场"
        chain.append({
            "event": title,
            "cause": "新闻事件",
            "effect": f"涉及 {sym_str}",
            "news_ids": [n.get("id", "")],
        })
    return chain


def _fallback_summary(news_list: list[dict]) -> str:
    """降级摘要"""
    top = news_list[0] if news_list else None
    if not top:
        return "本小时无重大事件"
    title = top.get("title", "")[:30]
    return f"本小时共 {len(news_list)} 条事件，重点：{title}"


# ── 主入口 ─────────────────────────────────────────────────

async def run_hourly_ai(hour_bucket: int):
    """每小时末执行：生成区域叙事 + 因果链"""
    print(f"[AINarrator] 开始生成 {time.strftime('%Y-%m-%d %H:00', time.localtime(hour_bucket))} 的 AI 叙事...")
    await asyncio.gather(
        generate_region_narratives(hour_bucket),
        generate_causal_chain(hour_bucket),
    )
    print(f"[AINarrator] 完成")


async def run_historical(hours: int = 24):
    """回填历史 N 小时"""
    current_hour = (int(time.time()) // 3600) * 3600
    for h in range(current_hour, current_hour - hours * 3600, -3600):
        await run_hourly_ai(h)


if __name__ == "__main__":
    print("[AINarrator] 开始回填...")
    asyncio.run(run_historical(hours=24))
    print("[AINarrator] 完成")
