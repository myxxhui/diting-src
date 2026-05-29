"""行情采集薄壳 — 委托 MarketQuoteClient。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §八 Q10]
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Union

from apps.common.market_quote import MarketQuoteClient
from apps.exit_engine.config import settings

if TYPE_CHECKING:
    from apps.exit_engine.data.mock_quote_fetcher import MockQuoteFetcher

logger = logging.getLogger(__name__)


class QuoteFetcher:
    """D4 行情刷新入口；内部走腾讯/新浪/东财多源降级。"""

    def __init__(self, redis_url: str | None = None):
        url = redis_url or settings.redis_url
        self._client = MarketQuoteClient(redis_url=url)

    def fetch_one(self, symbol: str, *, bypass_cache: bool = False) -> Optional[float]:
        quotes = self.fetch_batch([symbol], bypass_cache=bypass_cache)
        return quotes.get(symbol)

    def fetch_batch(
        self,
        symbols: list[str],
        *,
        bypass_cache: bool = False,
    ) -> dict[str, float]:
        if not symbols:
            return {}
        quotes = self._client.get_realtime(symbols, bypass_cache=bypass_cache)
        out: dict[str, float] = {}
        for sym, q in quotes.items():
            out[sym] = q.close
            logger.debug(
                "行情 symbol=%s close=%.4f source=%s stale=%s",
                sym, q.close, q.source, q.is_stale,
            )
        if len(out) < len(symbols):
            missing = set(symbols) - set(out.keys())
            logger.warning("行情部分缺失 symbols=%s", sorted(missing))
        return out

    def health(self):
        return self._client.health()


def build_fetcher(use_mock: bool = False) -> Union[QuoteFetcher, "MockQuoteFetcher"]:
    if use_mock:
        from apps.exit_engine.data.mock_quote_fetcher import MockQuoteFetcher

        return MockQuoteFetcher()
    return QuoteFetcher()
