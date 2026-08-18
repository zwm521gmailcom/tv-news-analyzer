import asyncio
import time
from typing import Optional
from config import settings
from db.repository import NewsRepository
from core.fetcher import TradingViewFetcher
from core.cookie_manager import CookieManager
from pipeline.orchestrator import Orchestrator
from display.console import ConsoleDisplay


def _get_current_hour_bucket() -> int:
    """获取当前小时桶（Unix 时间戳截断到小时）"""
    return (int(time.time()) // 3600) * 3600


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
        """每小时末运行 AI 叙事生成"""
        last_hour_bucket = _get_current_hour_bucket()
        last_global_run = 0  # 上次全局叙事生成的时间戳

        while not self._stop_event.is_set():
            current_hour = _get_current_hour_bucket()
            now = int(time.time())

            if current_hour > last_hour_bucket:
                # 新的一小时开始了，生成上一小时的 AI 叙事
                hour_to_process = last_hour_bucket
                print(f"[Scheduler] 检测到新小时 {time.strftime('%Y-%m-%d %H:00', time.localtime(hour_to_process))}，触发 AI 叙事生成...")
                try:
                    from pipeline.ai_narrator import run_hourly_ai
                    await run_hourly_ai(hour_to_process)
                    print(f"[Scheduler] AI 叙事生成完成")
                except Exception as e:
                    print(f"[Scheduler] AI 叙事生成失败: {e}")

                # 每 6 小时生成一次全局叙事
                if now - last_global_run >= 6 * 3600:
                    print(f"[Scheduler] 触发全局叙事生成...")
                    try:
                        from pipeline.global_narrative import run_global_narrative
                        await run_global_narrative(lookback_hours=24)
                        last_global_run = now
                        print(f"[Scheduler] 全局叙事生成完成")
                    except Exception as e:
                        print(f"[Scheduler] 全局叙事生成失败: {e}")

                last_hour_bucket = current_hour

            # 每分钟检查一次
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
