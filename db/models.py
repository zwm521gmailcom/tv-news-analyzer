from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class RawNews:
    # 只保存接口返回字段及由返回内容派生的字段，不保存 request-side 的 priority/format。
    id: str
    title: str
    urgency: int
    provider: str
    published: int                       # Unix 时间戳
    short_desc: Optional[str] = None     # 接口摘要（short_description）
    symbols: list[str] = field(default_factory=list)  # 接口 relatedSymbols 提取
    story_body: Optional[str] = None     # 详情接口正文，已本地转纯文本
    is_flash: bool = False               # 接口快讯标记
    lang: str = "en"                     # 本次请求语言，不是接口原生字段
    market: str = "unknown"              # 本地推断字段（symbols/provider/title）
    sector: Optional[str] = None         # 本地从 logoid:sector/* 提取
    corp_activity: Optional[str] = None  # 本地启发式字段（标题 / 正文 / path）
    country: Optional[str] = None        # 本地从 logoid:country/* 提取
    fetched_at: int = field(default_factory=lambda: int(time.time()))  # 本地抓取时间
    raw_json: Optional[str] = None       # 接口原始 payload


@dataclass
class GeoEvent:
    id: str
    news_id: str
    latitude: Optional[float]
    longitude: Optional[float]
    location_name: Optional[str]
    country_code: Optional[str]
    region: Optional[str]
    geom_source: str                     # "symbol_market" | "keyword_regex"
    urgency: int
    published: int
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class EventSummary:
    id: str
    hour_bucket: int                     # Unix 时间戳截断到小时
    top_events: list[dict]               # [{"news_id": "", "title": "", "urgency": 3, "summary": "", "symbols": []}]
    ai_narrative: Optional[str]          # AI 生成的一句话叙事
    event_count: int
    flash_count: int
    computed_at: int
    computed_by: str = "ollama"          # "ollama" | "keyword_fallback" | "realtime"


@dataclass
class EventRelation:
    id: str
    from_news_id: str
    to_news_id: str
    relation_type: str                  # "symbol_shared" | "time_proximate" | "causal_ai"
    confidence: float
    ai_explanation: Optional[str]
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class RegionNarrative:
    id: str
    hour_bucket: int
    region: str
    latitude: Optional[float]
    longitude: Optional[float]
    news_count: int
    top_events: list[dict]               # [{"news_id": "", "title": "", "urgency": 3}]
    ai_brief: Optional[str]              # AI 生成的一句话描述
    ai_reasoning: Optional[str]         # AI 推理过程
    urgency_score: float                # 0.0-1.0
    computed_at: int
    computed_by: str = "ollama"


@dataclass
class HourCausalNarrative:
    id: str
    hour_bucket: int
    ai_chain: list[dict]                # [{"event": "", "cause": "", "effect": "", "news_ids": []}]
    ai_summary: Optional[str]           # 一句话总摘要
    total_events: int
    computed_at: int
    computed_by: str = "ollama"
