"""共享行情入口 — D4/D3/D0/D2。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md]
"""
from apps.common.market_quote.client import MarketQuoteClient
from apps.common.market_quote.schemas import Kline, RealtimeQuote, SourceHealth

__all__ = ["MarketQuoteClient", "RealtimeQuote", "Kline", "SourceHealth"]
