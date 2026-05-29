"""MarketQuoteClient — 多源降级 + 断路器 + Redis 缓存。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §五 §七]
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional

import redis

from apps.common.market_quote.circuit_breaker import CircuitBreakerRegistry, get_breaker_registry
from apps.common.market_quote.exchange import validate_symbol
from apps.common.market_quote.schemas import Kline, RealtimeQuote, SourceHealth
from apps.common.market_quote.sources import eastmoney_list, sina, sina_kline, tencent, tencent_kline
from apps.common.market_quote.time_utils import kline_cache_ttl_sec

logger = logging.getLogger(__name__)

_RT_SOURCES = ("tencent", "sina", "eastmoney_list")
_KLINE_SOURCES = ("tencent_kline", "sina_kline")
_RT_CACHE_PREFIX = "quote:rt:"
_KLINE_CACHE_PREFIX = "quote:kline:"
_RT_TTL = 60


class MarketQuoteClient:
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        breaker: CircuitBreakerRegistry | None = None,
    ) -> None:
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.breaker = breaker or get_breaker_registry()

    def get_realtime(
        self,
        symbols: list[str],
        *,
        bypass_cache: bool = False,
    ) -> dict[str, RealtimeQuote]:
        if not symbols:
            return {}
        normalized = [validate_symbol(s) for s in symbols]
        result: dict[str, RealtimeQuote] = {}
        missing: list[str] = []

        if bypass_cache:
            missing = list(normalized)
        else:
            for sym in normalized:
                cached = self._cache_get_rt(sym)
                if cached is not None:
                    result[sym] = cached
                else:
                    missing.append(sym)

        if not missing:
            return result

        fetchers: list[tuple[str, Callable[[list[str]], dict[str, RealtimeQuote]]]] = [
            ("tencent", tencent.fetch_realtime),
            ("sina", sina.fetch_realtime),
            ("eastmoney_list", eastmoney_list.fetch_realtime),
        ]

        for source_name, fetch_fn in fetchers:
            still_need = [s for s in missing if s not in result]
            if not still_need:
                break
            if not self.breaker.can_execute(source_name):
                logger.debug("[market_quote] 跳过源 %s（断路器）", source_name)
                continue

            batch_result = self.breaker.call(source_name, lambda sn=still_need, fn=fetch_fn: fn(sn))
            if not batch_result:
                continue
            for sym, quote in batch_result.items():
                if sym in still_need:
                    result[sym] = quote
                    if not bypass_cache:
                        self._cache_set_rt(sym, quote)

        return result

    def get_recent_kline(self, symbol: str, days: int = 30) -> list[Kline]:
        sym = validate_symbol(symbol)
        if days <= 0:
            raise ValueError("days 须 > 0")

        cached = self._cache_get_kline(sym, days)
        if cached is not None:
            return cached

        fetchers: list[tuple[str, Callable[[str, int], list[Kline]]]] = [
            ("tencent_kline", tencent_kline.fetch_kline),
            ("sina_kline", sina_kline.fetch_kline),
        ]

        for source_name, fetch_fn in fetchers:
            if not self.breaker.can_execute(source_name):
                continue
            rows = self.breaker.call(source_name, lambda fn=fetch_fn: fn(sym, days))
            if rows:
                self._cache_set_kline(sym, days, rows)
                return rows
        return []

    def health(self) -> dict[str, SourceHealth]:
        all_sources = list(_RT_SOURCES) + list(_KLINE_SOURCES)
        return self.breaker.all_health(all_sources)

    def _cache_get_rt(self, symbol: str) -> Optional[RealtimeQuote]:
        try:
            raw = self.redis.get(_RT_CACHE_PREFIX + symbol)
            if raw:
                return RealtimeQuote.from_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis RT cache get 失败 %s: %s", symbol, exc)
        return None

    def _cache_set_rt(self, symbol: str, quote: RealtimeQuote) -> None:
        try:
            self.redis.setex(_RT_CACHE_PREFIX + symbol, _RT_TTL, quote.to_json())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis RT cache set 失败 %s: %s", symbol, exc)

    def _cache_get_kline(self, symbol: str, days: int) -> Optional[list[Kline]]:
        key = f"{_KLINE_CACHE_PREFIX}{symbol}:{days}"
        try:
            raw = self.redis.get(key)
            if raw:
                return [Kline.from_json(line) for line in json.loads(raw)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis kline cache get 失败 %s: %s", symbol, exc)
        return None

    def _cache_set_kline(self, symbol: str, days: int, rows: list[Kline]) -> None:
        key = f"{_KLINE_CACHE_PREFIX}{symbol}:{days}"
        try:
            payload = json.dumps([r.to_json() for r in rows], ensure_ascii=False)
            self.redis.setex(key, kline_cache_ttl_sec(), payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis kline cache set 失败 %s: %s", symbol, exc)
