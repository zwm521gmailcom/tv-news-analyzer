import asyncio
from typing import Optional, TYPE_CHECKING
from config import settings
from db.models import RawNews
from db.repository import NewsRepository
from display.console import ConsoleDisplay

if TYPE_CHECKING:
    from core.fetcher import TradingViewFetcher


class Orchestrator:
    """协调新闻抓取与存储流程"""

    def __init__(self, repo: NewsRepository, display: ConsoleDisplay,
                 fetcher: Optional["TradingViewFetcher"] = None):
        self.repo = repo
        self.display = display
        self.fetcher = fetcher

    async def process_news_batch(self, news_list: list[RawNews]) -> int:
        """处理一批新闻，返回新写入数量"""
        if not news_list:
            return 0

        # 去重：过滤已在 DB 中的 id
        ids = [n.id for n in news_list]
        new_ids = set(await self.repo.filter_new_ids(ids))
        new_news = [n for n in news_list if n.id in new_ids]

        if not new_news:
            return 0

        # 写入原始新闻
        inserted = await self.repo.save_news_batch(new_news)

        # 展示
        for n in new_news:
            self.display.show_raw(n)

        # 后台抓取正文，不阻塞主流程
        if settings.FETCH_STORY_BODY and self.fetcher:
            asyncio.create_task(self._fetch_bodies(new_news))

        return inserted

    async def _fetch_bodies(self, news_list: list[RawNews]) -> None:
        """后台逐条抓取正文，每条间隔 0.5s 避免请求过快"""
        for news in news_list:
            try:
                body = await self.fetcher.fetch_story_body(news.id, lang=news.lang)
                if body and len(body) > 10:
                    await self.repo.save_story_body(news.id, body)
                    news.story_body = body
            except Exception as e:
                print(f"[Body] 抓取失败 {news.id[:40]}: {e}")
            await asyncio.sleep(0.5)
