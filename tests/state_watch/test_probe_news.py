"""P2·新闻探针测试.

[Ref: 03_/03_维度三/.../step_02]
"""
from __future__ import annotations

import pytest

from apps.state_watch.probes.news import NewsProbe


@pytest.mark.asyncio
async def test_news_fetch_returns_aggregate():
    probe = NewsProbe()
    result = await probe.fetch("600519")
    assert result.success is True
    assert result.data["total_count_7d"] >= 1
    assert -1.0 <= result.data["sentiment_score_7d"] <= 1.0
    assert result.data["positive_count_7d"] >= 1
    assert result.data["latest_event"] is not None


@pytest.mark.asyncio
async def test_news_negative_aggregation():
    probe = NewsProbe()
    result = await probe.fetch("000001")
    assert result.success is True
    assert result.data["negative_count_7d"] >= 1


@pytest.mark.asyncio
async def test_news_unknown_symbol_returns_zero():
    probe = NewsProbe()
    result = await probe.fetch("UNKNOWN_X")
    assert result.success is True
    assert result.data["total_count_7d"] == 0
    assert result.data["sentiment_score_7d"] == 0.0


@pytest.mark.asyncio
async def test_news_metric_keys():
    probe = NewsProbe()
    result = await probe.fetch("300750")
    expected = {
        "sentiment_score_7d",
        "negative_count_7d",
        "positive_count_7d",
        "total_count_7d",
        "latest_event",
    }
    assert expected == set(result.data.keys())


@pytest.mark.asyncio
async def test_news_sentiment_neutral_when_empty():
    probe = NewsProbe()
    result = await probe.fetch("UNKNOWN_X")
    assert result.data["sentiment_score_7d"] == 0.0
    assert result.data["negative_count_7d"] == 0


@pytest.mark.asyncio
async def test_news_latest_event_structure():
    probe = NewsProbe()
    result = await probe.fetch("600519")
    assert result.success is True
    event = result.data["latest_event"]
    assert isinstance(event, dict)
    assert "title" in event
