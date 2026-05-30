from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class ETFQuote:
    """ETF 实时行情"""
    symbol: str
    price: float          # 当前价（元）
    open: float           # 开盘价（元）
    high: float           # 最高价（元）
    low: float            # 最低价（元）
    pre_close: float      # 昨收价（元）
    volume: int           # 成交量（手）
    amount: float         # 成交额（元）
    timestamp: str        # 时间戳


@dataclass
class ETFNav:
    """ETF 净值信息"""
    symbol: str
    nav: float            # 单位净值（元）
    price: float          # 市场价格（元）
    premium: float        # 溢价率（%，正数为溢价，负数为折价）
    timestamp: str


@dataclass
class ETFHistory:
    """ETF 历史行情"""
    date: str             # 日期 YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int           # 成交量（手）
    amount: float         # 成交额（元）


@dataclass
class ETFInfo:
    """ETF 基本信息"""
    symbol: str
    name: str             # ETF名称
    etf_type: str         # ETF类型（宽基、行业、主题等）
    size: float           # 规模（元）
    tracking_index: str   # 跟踪指数


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    url: str
    source: str
    publish_time: str
    summary: Optional[str] = None


@dataclass
class MarketSentiment:
    """市场情绪"""
    sentiment: str        # bullish, bearish, neutral
    score: int            # 0-100
    factors: List[str]


class AdapterError(Exception):
    """适配器错误基类"""

    def __init__(self, message: str, error_code: str = None, source: str = None):
        super().__init__(message)
        self.error_code = error_code
        self.source = source


class DataFetchError(AdapterError):
    """数据获取错误"""
    pass


class ServiceUnavailableError(AdapterError):
    """服务不可用错误"""
    pass
