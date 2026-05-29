"""MarketQuoteClient 降级链测试（mock 源）。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from apps.common.market_quote.circuit_breaker import CircuitBreakerRegistry
from apps.common.market_quote.client import MarketQuoteClient
from apps.common.market_quote.schemas import RealtimeQuote


def _quote(sym: str, source: str, close: float = 10.0) -> RealtimeQuote:
    return RealtimeQuote(
        symbol=sym,
        close=close,
        prev_close=close - 1,
        change_pct=0.01,
        volume=1000,
        timestamp=datetime(2026, 5, 23, 15, 0, 0),
        source=source,
        is_stale=False,
    )


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value


@pytest.fixture
def client():
    breaker = CircuitBreakerRegistry(fail_threshold=5, cool_down_sec=60)
    c = MarketQuoteClient(redis_url="redis://localhost:6379/0", breaker=breaker)
    c.redis = _FakeRedis()
    return c


def test_degradation_tencent_fail_sina_ok(client):
    with patch("apps.common.market_quote.client.tencent.fetch_realtime", return_value={}):
        with patch(
            "apps.common.market_quote.client.sina.fetch_realtime",
            return_value={"601138": _quote("601138", "sina")},
        ):
            r = client.get_realtime(["601138"], bypass_cache=True)
    assert "601138" in r
    assert r["601138"].source == "sina"


def test_degradation_all_fail(client):
    with patch("apps.common.market_quote.client.tencent.fetch_realtime", return_value={}):
        with patch("apps.common.market_quote.client.sina.fetch_realtime", return_value={}):
            with patch("apps.common.market_quote.client.eastmoney_list.fetch_realtime", return_value={}):
                r = client.get_realtime(["601138"], bypass_cache=True)
    assert r == {}
