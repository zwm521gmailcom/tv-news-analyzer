import asyncio
import json
import time
import aiohttp
from asyncio.subprocess import PIPE
from typing import Optional
from urllib.parse import urlencode
from config import settings
from core.cookie_manager import CookieManager
from core.raw_json_fields import (
    derive_fields_from_raw_item,
)
from db.models import RawNews

# ── 交易所 → 市场类型映射 ─────────────────────────────────────
_CRYPTO   = {'BINANCE','BYBIT','COINBASE','KRAKEN','OKX','KUCOIN','BITFINEX',
             'BITSTAMP','GEMINI','HUOBI','MEXC','GATE','BITMEX','DERIBIT'}
_FOREX    = {'FX','FX_IDC','OANDA','FXCM','FOREXCOM'}
_FUTURES  = {'COMEX','NYMEX','CME','CBOT','ICE','EUREX','SHFE','DCE','ZCE','CZCE','LME'}
_INDEX    = {'TVC','SP','DJ','FRED','CBOE'}
_STOCK    = {'NYSE','NASDAQ','AMEX','SSE','SZSE','HKEX','TSE','LSE','EURONEXT',
             'KRX','ASX','BSE','NSE','SGX','PSE','IDX','SET','KLSE','JSE',
             'TADAWUL','BVB','MOEX','BOVESPA','MIL','XETR','SIX','HSI',
             'MYX','OMXSTO','BME','GPW','CSE','QSE','PIL','VN','OSL',
             'CHX','MEMX','LSEETF','BATS','TVC','TWSE'}

# 标题关键词兜底（用于无 symbols 的新闻）
_TITLE_KEYWORDS = {
    'stock':   ['股票','A股','港股','美股','IPO','招股','上市','递表','创业板','科创板'],
    'futures': ['债券','国债','收益率','期货','原油','黄金'],
    'forex':   ['汇市','外汇','货币','汇率','美元','欧元','人民币'],
    'economic':['央行','美联储','GDP','通胀','加息','降息','经济'],
}

# 提供商名称 → 市场类型（兜底，无 symbols 时使用）
_PROVIDER_MARKET = {
    'crypto':  {'paNews','panews','cointelegraph','coindesk','newsBTC','beincrypto',
                'coinpedia','cryptoslate','cryptonews','decrypt','theblock','bitcoin.com',
                'coinmarketcal','ambcrypto','bitcoinist','cryptopotato','u.today',
                'FX168 Crypto','coinjournal'},
    'forex':   {'fx168','fxstreet','dailyfx','forexlive','forexcrunch','investing.com',
                'forexfactory'},
    'stock':   {'stocktwits','seekingalpha','motleyfool','benzinga','zacks','barrons',
                'marketbeat','stockstory','mfn by modular finance','quartr','access newswire',
                'globenewswire','prnewswire','businesswire','acn newswire',
                'asian corporate newswire','japan corporate news'},
    'economic':{'trading economics','imf','world bank','federal reserve'},
    'index':   {'marketwatch','barclays','s&p','moody\'s'},
}

# 标题关键词 → 市场类型（最后兜底）
_TITLE_KEYWORDS = {
    'crypto':  ['bitcoin','btc','ethereum','eth','crypto','blockchain','defi','nft',
                'altcoin','binance','solana','xrp','usdt','stablecoin','web3',
                '比特币','加密','区块链','以太坊'],
    'forex':   ['forex','currency','usd','eur','gbp','jpy','audusd','eurusd',
                '汇率','外汇','美元','欧元','人民币','汇市'],
    'futures': ['crude oil','gold','silver','oil futures','commodity','wheat','corn',
                'natural gas','黄金','原油','期货','大宗商品','白银','债券','国债','收益率'],
    'index':   ['s&p 500','nasdaq','dow jones','index','nikkei','hang seng',
                '指数','恒生','纳斯达克'],
    'stock':   ['股票','A股','港股','美股','IPO','招股','上市','递表','创业板','科创板'],
    'economic':['央行','美联储','GDP','通胀','加息','降息','经济'],
}


def _get_all_markets(related_symbols: list[dict]) -> set[str]:
    """返回新闻关联的所有市场类型集合"""
    markets = set()

    # 1. symbols 前缀
    for sym in related_symbols:
        sym_str = sym.get("symbol", "")
        if ':' in sym_str:
            ex = sym_str.split(':')[0].upper()
            if ex in _CRYPTO:   markets.add('crypto')
            elif ex in _FOREX:   markets.add('forex')
            elif ex in _FUTURES: markets.add('futures')
            elif ex in _INDEX:  markets.add('index')
            elif ex in _STOCK:  markets.add('stock')

    # 2. logoid 推断
    for sym in related_symbols:
        logoid = sym.get("logoid", "")
        if logoid.startswith("indices/"):
            markets.add('index')
        elif logoid.startswith("metal/") or logoid.startswith("commodity/"):
            markets.add('futures')

    return markets


def _extract_logoid_fields(related_symbols: list[dict]) -> tuple[Optional[str], Optional[str]]:
    """从 relatedSymbols 提取 sector / country。"""
    # 保留兼容接口，实际逻辑已统一到 core/raw_json_fields.py
    from core.raw_json_fields import extract_sector_country_from_related_symbols
    return extract_sector_country_from_related_symbols(related_symbols)


class TradingViewFetcher:
    def __init__(self, cookie_manager: CookieManager):
        self.cm = cookie_manager
        self._session: Optional[aiohttp.ClientSession] = None
        # 记录每种语言上次见到的最新 published 时间戳，用于增量过滤
        self._last_published: dict[str, int] = {}

    def _build_browser_headers(self, include_cookie: bool = True) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/147.0.0.0 Safari/537.36",
            "Referer": "https://www.tradingview.com/",
            "Origin": "https://www.tradingview.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if include_cookie:
            headers.update(self.cm.get_headers())
        return headers

    async def _curl_request_json(
        self,
        url: str,
        params: list[tuple[str, str]],
        *,
        include_cookie: bool = True,
        timeout_seconds: int = 15,
    ) -> tuple[int, dict]:
        query = urlencode(params, doseq=True)
        full_url = f"{url}?{query}" if query else url
        status_marker = "__TV_NEWS_STATUS__"

        cmd = [
            "curl",
            "-sS",
            "--compressed",
            "--max-time",
            str(timeout_seconds),
            "-w",
            f"\n{status_marker}%{{http_code}}\n",
        ]
        proxy = settings.HTTP_PROXY or None
        if proxy:
            cmd.extend(["--proxy", proxy])

        for name, value in self._build_browser_headers(include_cookie=include_cookie).items():
            cmd.extend(["-H", f"{name}: {value}"])

        cmd.append(full_url)

        proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace").strip()
            raise aiohttp.ClientError(f"curl 请求失败: {err_text or proc.returncode}")

        output = stdout.decode("utf-8", "replace")
        if status_marker not in output:
            raise aiohttp.ClientError("curl 响应缺少状态标记")
        body, status_text = output.rsplit(status_marker, 1)
        status_text = status_text.strip()
        if not status_text.isdigit():
            raise aiohttp.ClientError(f"无法解析 curl 状态码: {status_text!r}")
        status = int(status_text)
        body = body.rstrip("\r\n")
        if status != 200:
            return status, {}
        try:
            data = json.loads(body or "{}")
        except json.JSONDecodeError as e:
            raise aiohttp.ClientError(f"curl 响应不是有效 JSON: {e}") from e
        if not isinstance(data, dict):
            raise aiohttp.ClientError("curl 响应 JSON 不是对象")
        return status, data

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/147.0.0.0 Safari/537.36",
                "Referer": "https://www.tradingview.com/",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
            headers.update(self.cm.get_headers())
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    def _build_params(self, lang: str, cursor: Optional[str] = None) -> list:
        """构建请求参数（多值 filter 需合并为一个逗号分隔项）"""
        filter_values: list[str] = [f"lang:{lang}"]

        def append_csv_filter(prefix: str, values: list[str]) -> None:
            if values:
                filter_values.append(f"{prefix}:{','.join(sorted(values))}")

        append_csv_filter("symbol", settings.TV_FILTER_SYMBOLS)
        append_csv_filter("market", settings.TV_FILTER_MARKETS)
        append_csv_filter("corp_activity", settings.TV_FILTER_CORP_ACTIVITIES)
        append_csv_filter("economic_category", settings.TV_FILTER_ECONOMIC_CATEGORIES)
        append_csv_filter("provider", settings.TV_FILTER_PROVIDERS)

        filter_values.sort()

        # nonce 参数绕过 CDN 缓存（每次请求唯一）
        params = [
            ("client", "screener"),
            ("streaming", "true"),
            ("user_prostatus", "non_pro"),
            ("_", str(int(time.time() * 1000))),
        ]
        for fv in filter_values:
            params.append(("filter", fv))

        if cursor:
            params.append(("cursor", cursor))

        return params

    async def fetch_latest(self, lang: Optional[str] = None) -> list[RawNews]:
        """单语言轮询，支持多页，返回 RawNews 列表"""
        if lang is None:
            lang = settings.TV_FILTER_LANG
        url = settings.TV_NEWS_BASE_URL + settings.TV_NEWS_LIST_PATH

        all_results: list[RawNews] = []
        cursor: Optional[str] = None
        page = 0
        max_pages = settings.TV_MAX_PAGES
        since = self._last_published.get(lang, 0)  # 上次最新时间（0 = 首次全量）

        while True:
            params = self._build_params(lang, cursor)
            try:
                status, data = await self._curl_request_json(url, params, timeout_seconds=15)
                if status == 403:
                    self.cm.on_auth_error()
                    return await self._fetch_anonymous(lang)
                if status == 400 and page > 0:
                    break
                if status != 200:
                    raise aiohttp.ClientError(f"HTTP {status}")
            except aiohttp.ClientError as e:
                print(f"[Fetcher] 请求失败 lang={lang} 第{page+1}页: {e}")
                break

            items = self._parse_response(data, lang)

            if since > 0:
                # 非首次：只保留比上次更新的条目
                new_items = [n for n in items if n.published > since]
                all_results.extend(new_items)
                # 遇到不再是新条目时停止翻页（已按时间倒序排列）
                if len(new_items) < len(items):
                    break
            else:
                all_results.extend(items)

            page += 1

            next_cursor = data.get("pagination", {}).get("cursor")
            if not next_cursor or not items:
                break
            if max_pages and page >= max_pages:
                break
            cursor = next_cursor

        # 更新本语言的最新时间戳
        if all_results:
            self._last_published[lang] = max(n.published for n in all_results)
        elif since == 0 and not all_results:
            pass  # 首次抓到空，不更新
        # 非首次且无新增：不修改 _last_published（保持原值）

        return all_results

    async def fetch_all_langs(self) -> list[RawNews]:
        """并发抓取 TV_FETCH_LANGS 中所有语言的新闻并合并"""
        langs = settings.TV_FETCH_LANGS
        if not langs:
            langs = [settings.TV_FILTER_LANG]

        tasks = [self.fetch_latest(lang=lang) for lang in langs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[RawNews] = []
        for lang, result in zip(langs, results):
            if isinstance(result, Exception):
                print(f"[Fetcher] lang={lang} 抓取失败: {result}")
            else:
                merged.extend(result)
        return merged

    async def _fetch_anonymous(self, lang: str) -> list[RawNews]:
        """匿名模式重试（单页）"""
        url = settings.TV_NEWS_BASE_URL + settings.TV_NEWS_LIST_PATH
        params = self._build_params(lang)
        try:
            status, data = await self._curl_request_json(
                url,
                params,
                include_cookie=False,
                timeout_seconds=15,
            )
            if status != 200:
                raise aiohttp.ClientError(f"HTTP {status}")
            return self._parse_response(data, lang)
        except Exception as e:
            print(f"[Fetcher] 匿名重试失败 lang={lang}: {e}")
            return []

    async def fetch_story_body(self, news_id: str, lang: str = "en") -> Optional[str]:
        """抓取新闻正文（可选），lang 用于请求对应语言版本"""
        if not settings.FETCH_STORY_BODY:
            return None
        url = settings.TV_NEWS_BASE_URL + settings.TV_NEWS_DETAIL_PATH
        try:
            status, data = await self._curl_request_json(
                url,
                [("id", news_id), ("lang", lang)],
                timeout_seconds=10,
            )
            if status != 200:
                return None
            return self._extract_body_text(data)
        except Exception:
            return None

    def _parse_response(self, data: dict, lang: str = "en") -> list[RawNews]:
        items = data.get("items", [])
        result = []
        now = int(time.time())
        for item in items:
            provider = item.get("provider", {})
            related_symbols = item.get("relatedSymbols", [])
            symbols = [s.get("symbol", "") for s in related_symbols]
            pname = provider.get("name", provider.get("id", ""))
            title = item.get("title", "")

            # 获取所有市场，过滤只有 stock 的新闻
            all_markets = _get_all_markets(related_symbols)
            if all_markets == {'stock'}:
                # 只有 stock 一个市场，跳过
                continue

            derived = derive_fields_from_raw_item(item)
            result.append(RawNews(
                id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                short_desc=item.get("short_description") or "",
                urgency=item.get("urgency", 2),
                provider=str(provider.get("name") or provider.get("id") or ""),
                published=item.get("published", now),
                symbols=symbols,
                is_flash=bool(item.get("is_flash", False)),
                lang=lang,
                market=derived["market"] or "unknown",
                sector=derived["sector"],
                corp_activity=derived["corp_activity"],
                country=derived["country"],
                fetched_at=now,
                raw_json=json.dumps(item, ensure_ascii=False),
            ))
        return result

    def _extract_body_text(self, data: dict) -> str:
        """将 AST 结构转为纯文本"""
        texts = []

        def walk(node):
            if isinstance(node, str):
                texts.append(node)
            elif isinstance(node, dict):
                if node.get("type") == "p":
                    for child in node.get("children", []):
                        walk(child)
                    texts.append("\n")
                elif node.get("type") == "root":
                    for child in node.get("children", []):
                        walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        body = data.get("ast_description") or data.get("body", {})
        walk(body)
        return " ".join(t for t in texts if t.strip())

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
