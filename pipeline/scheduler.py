import asyncio
import time
from typing import Optional
from config import settings
from db.repository import NewsRepository
from core.fetcher import TradingViewFetcher
from core.cookie_manager import CookieManager
from pipeline.orchestrator import Orchestrator
from display.console import ConsoleDisplay


class Scheduler:
    """新闻轮询调度器"""

    def __init__(self, repo: NewsRepository, fetcher: TradingViewFetcher,
                 display: ConsoleDisplay, cookie_manager: Optional[CookieManager] = None):
        self.repo = repo
        self.fetcher = fetcher
        self.display = display
        self.orchestrator = Orchestrator(repo, display, fetcher)
        self._stop_event = asyncio.Event()
        self._price_fetcher = None
        if settings.ENABLE_PRICE_TRACKER and cookie_manager:
            from core.ws_fetcher import TVPriceFetcher
            self._price_fetcher = TVPriceFetcher(cookie_manager)

    async def run(self):
        """启动并发协程"""
        self.display.show_startup()
        coros = [self._poll_loop(), self._hourly_ai_loop()]
        if self._price_fetcher:
            coros.append(self._price_fetcher.run())
        await asyncio.gather(*coros)

    async def _poll_loop(self):
        """每 POLL_INTERVAL_SECONDS 秒轮询一次新闻"""
        for lang in settings.TV_FETCH_LANGS:
            saved = await self.repo.get_state(f"last_published_{lang}")
            if saved:
                self.fetcher._last_published[lang] = int(saved)

        while not self._stop_event.is_set():
            start = time.monotonic()
            try:
                news_list = await self.fetcher.fetch_all_langs()
                inserted = await self.orchestrator.process_news_batch(news_list)
                await self.repo.set_state("last_poll_time", str(int(time.time())))
                for lang, ts in self.fetcher._last_published.items():
                    await self.repo.set_state(f"last_published_{lang}", str(ts))
                self.display.show_poll_result(len(news_list), inserted)
            except Exception as e:
                print(f"[Scheduler] 轮询异常: {e}")

            elapsed = time.monotonic() - start
            wait = max(0.0, settings.POLL_INTERVAL_SECONDS - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    def stop(self):
        self._stop_event.set()
        if self._price_fetcher:
            asyncio.create_task(self._price_fetcher.stop())

    async def run_once(self):
        """单次执行（--once 模式）"""
        self.display.show_startup()
        news_list = await self.fetcher.fetch_all_langs()
        inserted = await self.orchestrator.process_news_batch(news_list)
        self.display.show_poll_result(len(news_list), inserted)
        print(f"[Scheduler] 单次完成，获取 {len(news_list)} 条，新增 {inserted} 条")

    async def _hourly_ai_loop(self):
        """
        AI 叙事生成调度：
        - 每 6 小时：全局叙事（24h 窗口）
        - 每天 04:00：4 个周期洞察（daily / 3day / weekly / monthly）+ 板块预测
        - Ollama ai_narrator 已废弃，hour 粒度叙事不再生成
        """
        last_global_run = 0  # 上次全局叙事时间戳
        last_period_run_date = None  # 上次跑周期洞察的日期（YYYY-MM-DD）

        while not self._stop_event.is_set():
            now = int(time.time())
            today_str = time.strftime("%Y-%m-%d", time.localtime(now))
            current_hour = int(time.strftime("%H", time.localtime(now)))

            # 每 6 小时跑全局叙事
            if now - last_global_run >= 6 * 3600:
                print(f"[Scheduler] 触发全局叙事生成...")
                try:
                    from pipeline.global_narrative import run_global_narrative
                    await run_global_narrative(lookback_hours=24)
                    last_global_run = now
                    print(f"[Scheduler] 全局叙事生成完成")
                except Exception as e:
                    print(f"[Scheduler] 全局叙事生成失败: {e}")

            # 每天 04:00 跑 4 个周期洞察
            if current_hour == 4 and last_period_run_date != today_str:
                print(f"[Scheduler] 触发多周期洞察（04:00 例行）...")
                try:
                    from pipeline.period_insights import get_all_periods
                    result = await get_all_periods()
                    for period, r in result.get("periods", {}).items():
                        status = "OK" if r.get("ok") else f"FAIL: {r.get('error')}"
                        print(f"[Scheduler] 周期 {period}: {status}")
                    last_period_run_date = today_str
                except Exception as e:
                    print(f"[Scheduler] 多周期洞察失败: {e}")
                    last_period_run_date = today_str  # 失败也标记，避免每分钟重试

            # 每分钟检查一次
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
