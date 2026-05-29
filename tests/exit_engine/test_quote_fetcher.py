"""QuoteFetcher 单元测试(使用 mock,避免外部网络).

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

import json
from pathlib import Path

from apps.exit_engine.data.mock_quote_fetcher import MockQuoteFetcher


def test_mock_fetch_one_returns_price():
    m = MockQuoteFetcher({"600519": 1500.0})
    assert m.fetch_one("600519") == 1500.0


def test_mock_fetch_one_unknown_returns_none():
    m = MockQuoteFetcher({"600519": 1500.0})
    assert m.fetch_one("999999") is None


def test_mock_fetch_batch():
    m = MockQuoteFetcher({"600519": 1500.0, "000858": 187.0, "601318": 45.0})
    out = m.fetch_batch(["600519", "000858", "999999"])
    assert out == {"600519": 1500.0, "000858": 187.0}


def test_default_fixture_loaded():
    fixture = Path(__file__).parent / "fixtures/quotes_mock.json"
    assert fixture.exists()
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert "600519" in data
    assert len(data) >= 10


def test_quote_fetcher_factory_returns_mock():
    from apps.exit_engine.data.quote_fetcher import build_fetcher

    fetcher = build_fetcher(use_mock=True)
    assert isinstance(fetcher, MockQuoteFetcher)
