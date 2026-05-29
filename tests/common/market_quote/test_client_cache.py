"""MarketQuoteClient Redis 缓存测试。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from apps.common.market_quote.circuit_breaker import CircuitBreakerRegistry
from apps.common.market_quote.client import MarketQuoteClient
from apps.common.market_quote.schemas import RealtimeQuote


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0

    def get(self, key: str):
        self.get_calls += 1
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self.set_calls += 1
        self.store[key] = value


@pytest.fixture
def client():
    breaker = CircuitBreakerRegistry()
    c = MarketQuoteClient(breaker=breaker)
    c.redis = _FakeRedis()
    return c


def _quote() -> RealtimeQuote:
    return RealtimeQuote(
        symbol="601138",
        close=67.16,
        prev_close=65.5,
        change_pct=0.025,
        volume=100,
        timestamp=datetime(2026, 5, 23, 15, 0, 0),
        source="tencent",
        is_stale=False,
    )


def test_cache_hit_skips_http(client):
    fetch_calls = {"n": 0}

    def _fetch(symbols):
        fetch_calls["n"] += 1
        return {"601138": _quote()}

    with patch("apps.common.market_quote.client.tencent.fetch_realtime", side_effect=_fetch):
        client.get_realtime(["601138"], bypass_cache=False)
        assert fetch_calls["n"] == 1
        n_before = fetch_calls["n"]
        client.get_realtime(["601138"], bypass_cache=False)
        assert fetch_calls["n"] == n_before


def test_bypass_cache_always_fetches(client):
    with patch(
        "apps.common.market_quote.client.tencent.fetch_realtime",
        return_value={"601138": _quote()},
    ) as mock_fetch:
        client.get_realtime(["601138"], bypass_cache=True)
        client.get_realtime(["601138"], bypass_cache=True)
        assert mock_fetch.call_count == 2
