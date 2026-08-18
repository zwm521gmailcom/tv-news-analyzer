#!/usr/bin/env python3
"""
批量回填 story_body（对已入库但无正文的历史新闻补抓详情）

用法：
  python3 scripts/backfill_story_body.py              # 默认回填最新 500 条
  python3 scripts/backfill_story_body.py --limit 200  # 指定条数
  python3 scripts/backfill_story_body.py --delay 1.0  # 每条间隔秒数（默认 0.8）
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, get_db
from db.repository import NewsRepository
from core.fetcher import TradingViewFetcher
from core.cookie_manager import CookieManager
from config import settings


async def main(limit: int, delay: float):
    # 强制开启正文抓取（不受 .env 限制）
    settings.FETCH_STORY_BODY = True

    await init_db()
    cm = CookieManager()
    cm.load()
    fetcher = TradingViewFetcher(cm)

    async with get_db() as db:
        repo = NewsRepository(db)
        items = await repo.get_news_without_body(limit=limit)

    print(f"待回填: {len(items)} 条（最多 {limit}）")
    if not items:
        print("无需回填，已退出。")
        return

    ok = fail = skip = 0
    async with get_db() as db:
        repo = NewsRepository(db)
        for i, (news_id, lang) in enumerate(items, 1):
            body = await fetcher.fetch_story_body(news_id, lang=lang)
            if body and len(body) > 10:
                await repo.save_story_body(news_id, body)
                ok += 1
            else:
                fail += 1

            if i % 50 == 0:
                pct = i / len(items) * 100
                print(f"  [{i:4d}/{len(items)}] {pct:.0f}%  成功={ok}  失败={fail}")

            await asyncio.sleep(delay)

    await fetcher.close()
    print(f"\n完成: 成功={ok}  失败={fail}  跳过={skip}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="批量回填新闻正文")
    ap.add_argument("--limit", type=int, default=500, help="最多回填条数（默认 500）")
    ap.add_argument("--delay", type=float, default=0.8, help="每条请求间隔秒数（默认 0.8）")
    asyncio.run(main(**vars(ap.parse_args())))
