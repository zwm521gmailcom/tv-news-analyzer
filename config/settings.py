import os
from dotenv import load_dotenv

load_dotenv()

# ── TradingView ───────────────────────────────────────────
TV_NEWS_BASE_URL = "https://news-mediator.tradingview.com"
TV_NEWS_LIST_PATH = "/news-flow/v2/news"
TV_NEWS_LIST_PATH_PUBLIC = "/public/news-flow/v2/news"
TV_NEWS_DETAIL_PATH = "/public/news/v1/story"

TV_FILTER_LANG = os.getenv("TV_FILTER_LANG", "en")   # 保留向后兼容


def _parse_list(env_key: str, default: str = "") -> list[str]:
    raw = os.getenv(env_key, default).strip()
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else []


TV_FETCH_LANGS: list[str] = _parse_list("TV_FETCH_LANGS", "en,zh-Hans")


# ── 新闻筛选自选表 ────────────────────────────────────────
TV_FILTER_SYMBOLS: list[str] = _parse_list("TV_FILTER_SYMBOLS", "")
TV_FILTER_MARKETS: list[str] = _parse_list(
    "TV_FILTER_MARKETS",
    "bond,corp_bond,crypto,economic,etf,forex,futures,index",
)
TV_FILTER_CORP_ACTIVITIES: list[str] = _parse_list("TV_FILTER_CORP_ACTIVITIES", "")
TV_FILTER_ECONOMIC_CATEGORIES: list[str] = _parse_list("TV_FILTER_ECONOMIC_CATEGORIES", "")
TV_FILTER_PROVIDERS: list[str] = _parse_list("TV_FILTER_PROVIDERS", "")

# 是否抓取新闻正文
FETCH_STORY_BODY = os.getenv("FETCH_STORY_BODY", "false").lower() == "true"

# ── Pipeline ──────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 60
TV_MAX_PAGES = 3
MIN_URGENCY = 1
BLOCKED_PROVIDERS: list[str] = []
BLOCKED_KEYWORDS: list[str] = ["advertisement", "sponsored", "press release"]

# ── Database ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "tv_news.db")
COOKIE_PATH = os.path.join(BASE_DIR, "data", "cookies.json")
LOG_PATH = os.path.join(BASE_DIR, "logs", "tv_news.log")
NEWS_RETENTION_DAYS = 30

# ── Proxy ─────────────────────────────────────────────────
HTTP_PROXY = os.getenv("HTTP_PROXY", os.getenv("ALL_PROXY", ""))

# ── WebSocket 实时行情 ────────────────────────────────────
TV_PRICE_SYMBOLS: list[str] = _parse_list(
    "TV_PRICE_SYMBOLS",
    "BINANCE:BTCUSDT,BINANCE:ETHUSDT,BINANCE:SOLUSDT,BINANCE:BNBUSDT,BINANCE:XRPUSDT"
)
ENABLE_PRICE_TRACKER = os.getenv("ENABLE_PRICE_TRACKER", "false").lower() == "true"

# ── AI Provider ────────────────────────────────────────────
# MiniMax API（用于 AI 叙事生成，替代 Ollama）
MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL: str = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic/v1")
MINIMAX_MODEL: str = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
