from __future__ import annotations

import re
from typing import Optional

# ── 交易所 → 市场类型映射 ─────────────────────────────────────
_CRYPTO = {
    "BINANCE", "BYBIT", "COINBASE", "KRAKEN", "OKX", "KUCOIN", "BITFINEX",
    "BITSTAMP", "GEMINI", "HUOBI", "MEXC", "GATE", "BITMEX", "DERIBIT",
}
_FOREX = {"FX", "FX_IDC", "OANDA", "FXCM", "FOREXCOM"}
_FUTURES = {"COMEX", "NYMEX", "CME", "CBOT", "ICE", "EUREX", "SHFE", "DCE", "ZCE", "CZCE", "LME"}
_INDEX = {"TVC", "SP", "DJ", "FRED", "CBOE"}
_STOCK = {
    "NYSE", "NASDAQ", "AMEX", "SSE", "SZSE", "HKEX", "TSE", "LSE", "EURONEXT",
    "KRX", "ASX", "BSE", "NSE", "SGX", "PSE", "IDX", "SET", "KLSE", "JSE",
    "TADAWUL", "BVB", "MOEX", "BOVESPA", "MIL", "XETR", "SIX", "HSI",
    "MYX", "OMXSTO", "BME", "GPW", "CSE", "QSE", "PIL", "VN", "OSL",
    "CHX", "MEMX", "LSEETF", "BATS", "TWSE",
}

_PROVIDER_MARKET = {
    "crypto": {
        "paNews", "panews", "cointelegraph", "coindesk", "newsBTC", "beincrypto",
        "coinpedia", "cryptoslate", "cryptonews", "decrypt", "theblock", "bitcoin.com",
        "coinmarketcal", "ambcrypto", "bitcoinist", "cryptopotato", "u.today",
        "FX168 Crypto", "coinjournal",
    },
    "forex": {
        "fx168", "fxstreet", "dailyfx", "forexlive", "forexcrunch", "investing.com",
        "forexfactory",
    },
    "stock": {
        "stocktwits", "seekingalpha", "motleyfool", "benzinga", "zacks", "barrons",
        "marketbeat", "stockstory", "mfn by modular finance", "quartr", "access newswire",
        "globenewswire", "prnewswire", "businesswire", "acn newswire",
        "asian corporate newswire", "japan corporate news",
    },
    "economic": {"trading economics", "imf", "world bank", "federal reserve"},
    "index": {"marketwatch", "barclays", "s&p", "moody's"},
}

_TITLE_KEYWORDS = {
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "nft",
        "altcoin", "binance", "solana", "xrp", "usdt", "stablecoin", "web3",
        "比特币", "加密", "区块链", "以太坊",
    ],
    "forex": [
        "forex", "currency", "usd", "eur", "gbp", "jpy", "audusd", "eurusd",
        "汇率", "外汇", "美元", "欧元", "人民币", "汇市",
    ],
    "futures": [
        "crude oil", "gold", "silver", "oil futures", "commodity", "wheat", "corn",
        "natural gas", "黄金", "原油", "期货", "大宗商品", "白银", "债券", "国债", "收益率",
    ],
    "index": [
        "s&p 500", "nasdaq", "dow jones", "index", "nikkei", "hang seng",
        "指数", "恒生", "纳斯达克",
    ],
    "stock": ["股票", "A股", "港股", "美股", "IPO", "招股", "上市", "递表", "创业板", "科创板"],
    "economic": ["央行", "美联储", "GDP", "通胀", "加息", "降息", "经济"],
}


def _iter_logoid_values(related_symbols: list[dict]) -> list[str]:
    values: list[str] = []
    for sym in related_symbols or []:
        if not isinstance(sym, dict):
            continue
        for key, value in sym.items():
            if key.endswith("logoid") and isinstance(value, str) and value:
                values.append(value)
    return values


def extract_sector_country_from_related_symbols(related_symbols: list[dict]) -> tuple[Optional[str], Optional[str]]:
    """
    从 relatedSymbols 里提取 sector 和 country。

    兼容以下键：
    - logoid
    - currency-logoid
    - base-currency-logoid
    """
    sector = None
    country = None

    for logoid in _iter_logoid_values(related_symbols):
        if logoid.startswith("sector/") and sector is None:
            sector = logoid.split("/", 1)[1]
        elif logoid.startswith("country/") and country is None:
            country = logoid.split("/", 1)[1]

    return sector, country


def infer_market_from_related_symbols(
    related_symbols: list[dict],
    provider: str = "",
    title: str = "",
) -> str:
    """
    市场类型推断，四级优先级：
    1. relatedSymbols 交易所前缀
    2. relatedSymbols logoid 推断（index/futures）
    3. 提供商名称匹配
    4. 标题关键词匹配
    """
    for sym in related_symbols or []:
        if not isinstance(sym, dict):
            continue
        sym_str = sym.get("symbol", "")
        if ":" in sym_str:
            ex = sym_str.split(":", 1)[0].upper()
            if ex in _CRYPTO:
                return "crypto"
            if ex in _FOREX:
                return "forex"
            if ex in _FUTURES:
                return "futures"
            if ex in _INDEX:
                return "index"
            if ex in _STOCK:
                return "stock"

    for sym in related_symbols or []:
        if not isinstance(sym, dict):
            continue
        logoid = sym.get("logoid", "")
        if logoid.startswith("indices/"):
            return "index"
        if logoid.startswith("metal/") or logoid.startswith("commodity/"):
            return "futures"

    p = (provider or "").lower()
    for market, names in _PROVIDER_MARKET.items():
        if any(n.lower() in p for n in names):
            return market

    t = (title or "").lower()
    for market, keywords in _TITLE_KEYWORDS.items():
        if any(kw.lower() in t for kw in keywords):
            return market

    return "unknown"


def derive_market_sector_country_from_raw_item(item: dict) -> dict[str, Optional[str]]:
    """
    兼容旧入口：只返回 market / sector / country。
    """
    derived = derive_fields_from_raw_item(item)
    return {
        "market": derived["market"],
        "sector": derived["sector"],
        "country": derived["country"],
    }


_CORP_ACTIVITY_PATTERNS: list[tuple[str, list[str]]] = [
    ("mergers_and_acquisitions", [
        r"\bacquisition\b", r"\bacquire\b", r"\bacquired\b", r"\bmerger\b",
        r"\btakeover\b", r"\bbuyout\b", r"\bdeal\b", r"并购", r"收购", r"合并",
    ]),
    ("dividends", [
        r"\bdividend\b", r"\bdividends\b", r"\bex-dividend\b", r"\bpayout\b",
        r"股息", r"分红", r"派息",
    ]),
    ("buybacks", [
        r"\bbuyback\b", r"\brepurchase\b", r"\bshare repurchase\b", r"回购",
    ]),
    ("splits", [
        r"\bsplit\b", r"\breverse split\b", r"\bstock split\b", r"拆股",
    ]),
    ("ipo", [
        r"\bipo\b", r"\bpublic offering\b", r"\blisting\b", r"首次公开", r"上市", r"招股",
    ]),
    ("earnings", [
        r"\bearnings\b", r"\bresults\b", r"\bquarterly results\b", r"\bq[1-4]\b",
        r"财报", r"业绩", r"季度", r"利润", r"营收",
    ]),
    ("guidance", [
        r"\bguidance\b", r"\boutlook\b", r"\bforecast\b", r"\braises guidance\b",
        r"指引", r"展望",
    ]),
]


def infer_corp_activity_from_text(title: str = "", story_body: str = "", story_path: str = "") -> Optional[str]:
    """
    通过标题 / 正文 / path 轻量推断公司活动类型。

    这是启发式结果，不是 TradingView 原始字段。
    """
    text = " ".join(part for part in [title, story_body, story_path] if part).lower()
    if not text:
        return None

    for activity, patterns in _CORP_ACTIVITY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return activity
    return None


def derive_fields_from_raw_item(
    item: dict,
    story_body: str = "",
) -> dict[str, Optional[str]]:
    """
    从 TradingView 原始 item + 本地正文提取可回填字段。
    """
    provider = item.get("provider", {})
    if isinstance(provider, dict):
        provider_name = str(provider.get("name") or provider.get("id") or "")
    else:
        provider_name = str(provider or "")

    related_symbols = item.get("relatedSymbols", []) or []
    title = str(item.get("title") or "")
    story_path = str(item.get("storyPath") or "")
    market = infer_market_from_related_symbols(related_symbols, provider_name, title)
    sector, country = extract_sector_country_from_related_symbols(related_symbols)
    corp_activity = infer_corp_activity_from_text(title, story_body, story_path)
    return {
        "market": market,
        "sector": sector,
        "country": country,
        "corp_activity": corp_activity,
    }
