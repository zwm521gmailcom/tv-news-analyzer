"""
地理位置提取器 — 纯规则，无需 AI。

从新闻的 symbols、标题、正文中提取事件发生的地理位置，
返回 GeoEvent 对象（含纬度/经度/地名/国家代码/地区）。
"""

import re
import time
from typing import Optional

from db.models import RawNews, GeoEvent


# ── 策略1: 交易所/平台 → 已知城市坐标 ───────────────────────
# 按优先级排列
SYMBOL_LOCATION_MAP: dict[str, tuple[float, float, str, str]] = {
    # 加密货币交易所
    "BINANCE":   (31.2304, 121.4737, "Shanghai, CN",   "CN"),
    "COINBASE":  (37.7749, -122.4194, "San Francisco, US", "US"),
    "KRAKEN":    (37.7749, -122.4194, "San Francisco, US", "US"),
    "BITSTAMP":  (46.2044,   6.1432, "Zurich, CH",       "CH"),
    "BYBIT":     (31.2304, 121.4737, "Shanghai, CN",      "CN"),
    "OKX":       (31.2304, 121.4737, "Shanghai, CN",      "CN"),
    "HUOBI":     (31.2304, 121.4737, "Shanghai, CN",      "CN"),
    "KUCON":     (31.2304, 121.4737, "Shanghai, CN",      "CN"),
    "CRYPTO":    (37.7749, -122.4194, "San Francisco, US", "US"),
    # A股
    "SSE":       (31.2304, 121.4737, "Shanghai, CN",      "CN"),
    "SZSE":      (22.5431, 114.0579, "Shenzhen, CN",       "CN"),
    # 港股
    "HKEX":      (22.2855, 114.1577, "Hong Kong, HK",     "HK"),
    "SEHK":      (22.2855, 114.1577, "Hong Kong, HK",     "HK"),
    # 美股
    "NYSE":      (40.7128, -74.0060, "New York, US",      "US"),
    "NASDAQ":    (40.7128, -74.0060, "New York, US",      "US"),
    "AMEX":      (40.7128, -74.0060, "New York, US",      "US"),
    # 欧洲
    "LSE":       (51.5074,  -0.1278, "London, UK",        "UK"),
    "EURONEXT":  (52.3667,   4.9000, "Amsterdam, NL",     "NL"),
    "XETR":      (50.1109,   8.6821, "Frankfurt, DE",    "DE"),
    "XPAR":      (48.8566,   2.3522, "Paris, FR",        "FR"),
    "MIL":       (45.4642,   9.1900, "Milan, IT",         "IT"),
    "BMEX":      (40.4168,  -3.7038, "Madrid, ES",       "ES"),
    # 亚洲
    "TSE":       (35.6762, 139.6503, "Tokyo, JP",         "JP"),
    "KRX":       (37.5665, 126.9780, "Seoul, KR",         "KR"),
    "SGX":        (1.3521, 103.8198, "Singapore, SG",    "SG"),
    "ASX":      (-33.8688, 151.2093, "Sydney, AU",        "AU"),
    "NSE":      (28.6139,  77.2090, "New Delhi, IN",      "IN"),
    "BSE":      (19.0760,  72.8777, "Mumbai, IN",         "IN"),
    # 宏观经济/央行
    "ECONOMICS": (38.9072, -77.0369, "Washington DC, US", "US"),
    "FED":      (38.9072, -77.0369, "Washington DC, US", "US"),
    "ECB":      (50.1109,   8.6821, "Frankfurt, DE",     "DE"),
    "BOJ":      (35.6762, 139.6503, "Tokyo, JP",         "JP"),
    "PBOC":     (39.9042, 116.4074, "Beijing, CN",       "CN"),
    "BOE":      (51.5074,  -0.1278, "London, UK",         "UK"),
    "RBA":     (-33.8688, 151.2093, "Sydney, AU",         "AU"),
    "BOC":      (45.4215, -75.6972, "Ottawa, CA",         "CA"),
    "RBNZ":    (-36.8485, 174.7633, "Wellington, NZ",    "NZ"),
}

# ── 策略2: 国家/地区关键词 → 坐标 ───────────────────────────
# (正则模式, 纬度, 经度, 地名, 国家代码, 地区)
COUNTRY_PATTERNS: list[tuple[re.Pattern, float, float, str, str, str]] = [
    # 中东
    (re.compile(r'\bIran\b', re.IGNORECASE),         35.6892,  51.3890, "Tehran, IR",         "IR", "Middle East"),
    (re.compile(r'\bIranian\b', re.IGNORECASE),      35.6892,  51.3890, "Tehran, IR",         "IR", "Middle East"),
    (re.compile(r'\bIsrael\b', re.IGNORECASE),        31.7683,  35.2137, "Jerusalem, IL",      "IL", "Middle East"),
    (re.compile(r'\bIsraeli\b', re.IGNORECASE),       31.7683,  35.2137, "Jerusalem, IL",      "IL", "Middle East"),
    (re.compile(r'\bSaudi Arabia\b', re.IGNORECASE),  23.8859,  45.0790, "Riyadh, SA",         "SA", "Middle East"),
    (re.compile(r'\bSaudi\b', re.IGNORECASE),          23.8859,  45.0790, "Riyadh, SA",         "SA", "Middle East"),
    (re.compile(r'\bUAE\b', re.IGNORECASE),            25.2048,  55.2708, "Dubai, AE",          "AE", "Middle East"),
    (re.compile(r'\bUnited Arab Emirates\b', re.I),   25.2048,  55.2708, "Dubai, AE",          "AE", "Middle East"),
    (re.compile(r'\bQatar\b', re.IGNORECASE),          25.2854,  51.5310, "Doha, QA",           "QA", "Middle East"),
    (re.compile(r'\bIraq\b', re.IGNORECASE),           33.3152,  44.3661, "Baghdad, IQ",        "IQ", "Middle East"),
    (re.compile(r'\bOPEC\b', re.IGNORECASE),           25.2048,  55.2708, "Dubai, AE",          "AE", "Middle East"),
    (re.compile(r'\bMiddle East\b', re.IGNORECASE),    25.2048,  55.2708, "Dubai, AE",          "AE", "Middle East"),
    (re.compile(r'\bGulf\b', re.IGNORECASE),           25.2048,  55.2708, "Dubai, AE",          "AE", "Middle East"),
    (re.compile(r'\bLebanon\b', re.IGNORECASE),        33.8886,  35.4958, "Beirut, LB",         "LB", "Middle East"),
    (re.compile(r'\bYemen\b', re.IGNORECASE),          15.3694,  48.1734, "Sanaa, YE",          "YE", "Middle East"),
    (re.compile(r'\bSyria\b', re.IGNORECASE),          33.5138,  36.2765, "Damascus, SY",       "SY", "Middle East"),

    # 亚太
    (re.compile(r'\bChina\b', re.IGNORECASE),          35.8617, 104.1954, "Beijing, CN",        "CN", "Asia"),
    (re.compile(r'\bChinese\b', re.IGNORECASE),        35.8617, 104.1954, "Beijing, CN",        "CN", "Asia"),
    (re.compile(r'\bBeijing\b', re.IGNORECASE),        39.9042, 116.4074, "Beijing, CN",        "CN", "Asia"),
    (re.compile(r'\bShanghai\b', re.IGNORECASE),       31.2304, 121.4737, "Shanghai, CN",       "CN", "Asia"),
    (re.compile(r'\bShenzhen\b', re.IGNORECASE),       22.5431, 114.0579, "Shenzhen, CN",       "CN", "Asia"),
    (re.compile(r'\bHong Kong\b', re.IGNORECASE),     22.2855, 114.1577, "Hong Kong, HK",     "HK", "Asia"),
    (re.compile(r'\bJapan\b', re.IGNORECASE),          36.2048, 138.2529, "Tokyo, JP",          "JP", "Asia"),
    (re.compile(r'\bJapanese\b', re.IGNORECASE),       36.2048, 138.2529, "Tokyo, JP",          "JP", "Asia"),
    (re.compile(r'\bTokyo\b', re.IGNORECASE),          35.6762, 139.6503, "Tokyo, JP",          "JP", "Asia"),
    (re.compile(r'\bSouth Korea\b', re.IGNORECASE),   37.5665, 126.9780, "Seoul, KR",          "KR", "Asia"),
    (re.compile(r'\bKorea\b', re.IGNORECASE),         37.5665, 126.9780, "Seoul, KR",          "KR", "Asia"),
    (re.compile(r'\bSeoul\b', re.IGNORECASE),         37.5665, 126.9780, "Seoul, KR",          "KR", "Asia"),
    (re.compile(r'\bTaiwan\b', re.IGNORECASE),         25.0330, 121.5654, "Taipei, TW",         "TW", "Asia"),
    (re.compile(r'\bIndia\b', re.IGNORECASE),          20.5937,  78.9629, "New Delhi, IN",      "IN", "Asia"),
    (re.compile(r'\bIndian\b', re.IGNORECASE),         20.5937,  78.9629, "New Delhi, IN",      "IN", "Asia"),
    (re.compile(r'\bSingapore\b', re.IGNORECASE),      1.3521, 103.8198, "Singapore, SG",      "SG", "Asia"),
    (re.compile(r'\bAustralia\b', re.IGNORECASE),    -25.2744, 133.7751, "Canberra, AU",       "AU", "Asia"),
    (re.compile(r'\bAustralian\b', re.IGNORECASE),    -25.2744, 133.7751, "Canberra, AU",       "AU", "Asia"),
    (re.compile(r'\bASEAN\b', re.IGNORECASE),           1.3521, 103.8198, "Singapore, SG",      "SG", "Asia"),
    (re.compile(r'\bSoutheast Asia\b', re.IGNORECASE), 12.5637, 104.9910, "Bangkok, TH",        "TH", "Asia"),

    # 欧美
    (re.compile(r'\bUnited States\b', re.IGNORECASE),  38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bUS\b'),                            38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bUSA\b'),                           38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bAmerica\b', re.IGNORECASE),        38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bAmerican\b', re.IGNORECASE),        38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bWashington\b', re.IGNORECASE),     38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bNew York\b', re.IGNORECASE),       40.7128, -74.0060, "New York, US",        "US", "North America"),
    (re.compile(r'\bWall Street\b', re.IGNORECASE),   40.7128, -74.0060, "New York, US",        "US", "North America"),
    (re.compile(r'\bFed\b', re.IGNORECASE),            38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bTreasury\b', re.IGNORECASE),      38.9072, -77.0369, "Washington DC, US",   "US", "North America"),
    (re.compile(r'\bUK\b', re.IGNORECASE),              51.5074,  -0.1278, "London, UK",          "UK", "Europe"),
    (re.compile(r'\bBritain\b', re.IGNORECASE),         51.5074,  -0.1278, "London, UK",          "UK", "Europe"),
    (re.compile(r'\bBritish\b', re.IGNORECASE),         51.5074,  -0.1278, "London, UK",          "UK", "Europe"),
    (re.compile(r'\bLondon\b', re.IGNORECASE),         51.5074,  -0.1278, "London, UK",          "UK", "Europe"),
    (re.compile(r'\bGermany\b', re.IGNORECASE),         52.5200,  13.4050, "Berlin, DE",          "DE", "Europe"),
    (re.compile(r'\bGerman\b', re.IGNORECASE),         52.5200,  13.4050, "Berlin, DE",          "DE", "Europe"),
    (re.compile(r'\bBerlin\b', re.IGNORECASE),         52.5200,  13.4050, "Berlin, DE",          "DE", "Europe"),
    (re.compile(r'\bFrance\b', re.IGNORECASE),         48.8566,   2.3522, "Paris, FR",          "FR", "Europe"),
    (re.compile(r'\bFrench\b', re.IGNORECASE),         48.8566,   2.3522, "Paris, FR",          "FR", "Europe"),
    (re.compile(r'\bParis\b', re.IGNORECASE),          48.8566,   2.3522, "Paris, FR",          "FR", "Europe"),
    (re.compile(r'\bEurope\b', re.IGNORECASE),         50.8000,   4.4000, "Brussels, EU",       "EU", "Europe"),
    (re.compile(r'\bEuropean Union\b', re.IGNORECASE), 50.8000,  4.4000, "Brussels, EU",       "EU", "Europe"),
    (re.compile(r'\bECB\b', re.IGNORECASE),            50.1109,   8.6821, "Frankfurt, DE",      "DE", "Europe"),
    (re.compile(r'\bEuro Zone\b', re.IGNORECASE),     50.1109,   8.6821, "Frankfurt, DE",      "DE", "Europe"),
    (re.compile(r'\bSwitzerland\b', re.IGNORECASE),    46.9480,   7.4474, "Bern, CH",           "CH", "Europe"),
    (re.compile(r'\bSwiss\b', re.IGNORECASE),         46.9480,   7.4474, "Bern, CH",           "CH", "Europe"),
    (re.compile(r'\bRussia\b', re.IGNORECASE),         55.7558,  37.6173, "Moscow, RU",         "RU", "Europe"),
    (re.compile(r'\bRussian\b', re.IGNORECASE),        55.7558,  37.6173, "Moscow, RU",         "RU", "Europe"),
    (re.compile(r'\bMoscow\b', re.IGNORECASE),         55.7558,  37.6173, "Moscow, RU",         "RU", "Europe"),
    (re.compile(r'\bCanada\b', re.IGNORECASE),         45.4215, -75.6972, "Ottawa, CA",         "CA", "North America"),
    (re.compile(r'\bCanadian\b', re.IGNORECASE),       45.4215, -75.6972, "Ottawa, CA",         "CA", "North America"),
    (re.compile(r'\bMexico\b', re.IGNORECASE),         19.4326, -99.1332, "Mexico City, MX",    "MX", "North America"),

    # 其他
    (re.compile(r'\bBrazil\b', re.IGNORECASE),        -14.2350, -51.9253, "Brasilia, BR",       "BR", "South America"),
    (re.compile(r'\bLatin America\b', re.IGNORECASE), -23.5505, -46.6333, "Sao Paulo, BR",     "BR", "south America"),
    (re.compile(r'\bOPEC\b', re.IGNORECASE),           25.2048,  55.2708, "Dubai, AE",           "AE", "Middle East"),
    (re.compile(r'\bHouthi\b', re.IGNORECASE),         15.3694,  48.1734, "Sanaa, YE",          "YE", "Middle East"),
    (re.compile(r'\bGaza\b', re.IGNORECASE),           31.5017,  34.4618, "Gaza, PS",            "PS", "Middle East"),
    (re.compile(r'\bHezbollah\b', re.IGNORECASE),     33.8886,  35.4958, "Beirut, LB",         "LB", "Middle East"),
    (re.compile(r'\bTrump\b', re.IGNORECASE),          38.9072, -77.0369, "Washington DC, US",  "US", "North America"),
    (re.compile(r'\bPutin\b', re.IGNORECASE),          55.7558,  37.6173, "Moscow, RU",         "RU", "Europe"),
    (re.compile(r'\bMusk\b', re.IGNORECASE),           37.7749, -122.4194, "San Francisco, US",  "US", "North America"),
    (re.compile(r'\bZelenski\b', re.IGNORECASE),       50.4501,  30.5234, "Kyiv, UA",            "UA", "Europe"),
    (re.compile(r'\bUkraine\b', re.IGNORECASE),         50.4501,  30.5234, "Kyiv, UA",            "UA", "Europe"),
    (re.compile(r'\bNord Stream\b', re.IGNORECASE),   53.5488,   9.9876, "Hamburg, DE",        "DE", "Europe"),
    (re.compile(r'\bHolhorst\b', re.IGNORECASE),       52.5200,  13.4050, "Berlin, DE",          "DE", "Europe"),
]


def _region_for_country(country_code: str) -> str:
    """根据国家代码返回地区分类"""
    mapping = {
        "IR": "Middle East", "IL": "Middle East", "SA": "Middle East",
        "AE": "Middle East", "QA": "Middle East", "IQ": "Middle East",
        "YE": "Middle East", "LB": "Middle East", "SY": "Middle East",
        "PS": "Middle East",
        "CN": "Asia", "HK": "Asia", "TW": "Asia", "JP": "Asia",
        "KR": "Asia", "IN": "Asia", "SG": "Asia", "AU": "Asia",
        "TH": "Asia",
        "US": "North America", "CA": "North America", "MX": "North America",
        "UK": "Europe", "DE": "Europe", "FR": "Europe", "CH": "Europe",
        "IT": "Europe", "ES": "Europe", "NL": "Europe", "RU": "Europe",
        "UA": "Europe", "EU": "Europe",
        "BR": "South America",
    }
    return mapping.get(country_code, "Other")


def extract_geo(news: RawNews) -> Optional[GeoEvent]:
    """
    综合两条策略提取地理位置，返回 GeoEvent 或 None。
    优先级: symbol市场定位 > title关键词 > short_desc关键词 > story_body关键词
    """
    # ── 策略1: 从 symbols 推断 ───────────────────────────────
    if news.symbols:
        for sym in news.symbols:
            # 提取交易所前缀
            prefix = sym.split(":")[0].upper()
            if prefix in SYMBOL_LOCATION_MAP:
                lat, lng, name, cc = SYMBOL_LOCATION_MAP[prefix]
                return GeoEvent(
                    id=f"geo_{news.id}",
                    news_id=news.id,
                    latitude=lat,
                    longitude=lng,
                    location_name=name,
                    country_code=cc,
                    region=_region_for_country(cc),
                    geom_source="symbol_market",
                    urgency=news.urgency,
                    published=news.published,
                    created_at=int(time.time()),
                )

    # ── 策略2: 从文本关键词匹配 ──────────────────────────────
    for text_field in [news.title, news.short_desc or "", news.story_body or ""]:
        for pattern, lat, lng, name, cc, region in COUNTRY_PATTERNS:
            if pattern.search(text_field):
                return GeoEvent(
                    id=f"geo_{news.id}",
                    news_id=news.id,
                    latitude=lat,
                    longitude=lng,
                    location_name=name,
                    country_code=cc,
                    region=region,
                    geom_source="keyword_regex",
                    urgency=news.urgency,
                    published=news.published,
                    created_at=int(time.time()),
                )

    return None
