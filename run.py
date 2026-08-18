#!/usr/bin/env python3
"""
TradingView News Monitor
用法:
  python run.py                          # 持续运行
  python run.py --once                   # 单次获取
  python run.py --query                  # 查询最近 24h 新闻
  python run.py --query --hours 12       # 查询最近 12h
  python run.py --query --symbol BTCUSDT --limit 10
"""
import asyncio
import argparse
import signal
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings
from db.database import get_db, init_db
from db.repository import NewsRepository
from core.cookie_manager import CookieManager
from core.fetcher import TradingViewFetcher
from display.console import ConsoleDisplay
from pipeline.scheduler import Scheduler


def parse_args():
    parser = argparse.ArgumentParser(description="TradingView News Monitor")
    parser.add_argument("--once", action="store_true", help="单次运行后退出")
    parser.add_argument("--query", action="store_true", help="查询模式")
    parser.add_argument("--hours", type=int, default=24, help="查询最近 N 小时（默认 24）")
    parser.add_argument("--symbol", type=str, help="过滤交易对（如 BTCUSDT）")
    parser.add_argument("--lang", choices=["en", "zh-Hans"], help="过滤语言来源")
    parser.add_argument("--market", choices=["crypto","stock","forex","futures","bond","etf","index","unknown"],
                        help="过滤市场类型")
    parser.add_argument("--limit", type=int, default=20, help="返回条数（默认 20）")
    return parser.parse_args()


async def run_query(args):
    """查询模式"""
    display = ConsoleDisplay()
    async with get_db() as db:
        repo = NewsRepository(db)
        results, total = await repo.query_raw_news(
            hours=args.hours,
            lang=args.lang,
            market=args.market,
            symbol=args.symbol,
            limit=args.limit,
        )
        display.show_raw_list(results, total)


async def _backfill_loop(fetcher, items, delay):
    """后台逐条回填正文，独立 DB session（不依赖外层 repo），间隔 delay 秒防限速"""
    ok = fail = 0
    total = len(items)
    try:
        async with get_db() as db:
            repo = NewsRepository(db)
            for i, (news_id, lang) in enumerate(items, 1):
                try:
                    body = await fetcher.fetch_story_body(news_id, lang=lang)
                    if body and len(body) > 10:
                        await repo.save_story_body(news_id, body)
                        ok += 1
                    else:
                        fail += 1
                except Exception as e:
                    fail += 1
                    if i % 100 == 0:
                        print(f"[boot-backfill] 抓取失败 {news_id[:20]}: {e}")
                if i % 50 == 0:
                    pct = i / total * 100
                    print(f"[boot-backfill] [{i:4d}/{total}] {pct:.0f}%  成功={ok} 失败={fail}")
                await asyncio.sleep(delay)
    except asyncio.CancelledError:
        print(f"[boot-backfill] 被中断（成功={ok} 失败={fail}）")
        raise
    print(f"[boot-backfill] 完成: 成功={ok} 失败={fail}")


async def boot_backfill_if_needed(repo, fetcher, *, threshold=50, limit=500, delay=1.0):
    """启动时检测未回填正文数量：超过 threshold 就启动后台回填任务（不阻塞主流程）

    安全保证：
    1. 低于 threshold 跳过（避免无谓的 API 调用）
    2. 用 create_task 后台跑，不阻塞 News 启动
    3. delay=1.0s 保守间隔，避免被 API 限速
    4. task 内部用独立 DB session，不与主流程的 repo 冲突
    5. 跑一次后即退出，不循环（避免无限重试）
    """
    try:
        items = await repo.get_news_without_body(limit=limit)
    except Exception as e:
        print(f"[boot-backfill] 检测失败: {e}")
        return
    if len(items) < threshold:
        print(f"[boot-backfill] {len(items)} 条未回填，少于阈值 {threshold}，跳过自动回填")
        return
    print(f"[boot-backfill] 检测到 {len(items)} 条新闻未回填正文（> {threshold} 阈值），自动启动后台回填（每条 {delay}s）")
    asyncio.create_task(_backfill_loop(fetcher, items, delay))


async def run_monitor(once: bool = False):
    """监控模式（持续或单次）"""
    await init_db()

    cookie_manager = CookieManager()
    cookie_manager.load()

    display = ConsoleDisplay()
    fetcher = TradingViewFetcher(cookie_manager)

    async with get_db() as db:
        repo = NewsRepository(db)
        scheduler = Scheduler(repo, fetcher, display)

        # 启动时自动回填（如有需要）— 不阻塞主流程
        await boot_backfill_if_needed(repo, fetcher, threshold=50, limit=500, delay=1.0)

        if once:
            await scheduler.run_once()
        else:
            loop = asyncio.get_event_loop()

            def handle_sigint():
                print("\n[run] 收到停止信号，正在退出...")
                scheduler.stop()

            try:
                loop.add_signal_handler(signal.SIGINT, handle_sigint)
                loop.add_signal_handler(signal.SIGTERM, handle_sigint)
            except NotImplementedError:
                pass

            await scheduler.run()

    await fetcher.close()


def main():
    args = parse_args()

    if args.query:
        asyncio.run(run_query(args))
    else:
        asyncio.run(run_monitor(once=args.once))


if __name__ == "__main__":
    main()
