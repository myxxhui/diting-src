"""insider_sell_actual T1 算子单测。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.copilot.modules.executing.indicator_nodes import build_insider_sell_actual_node
from apps.copilot.modules.executing.insider_sell_actual import (
    CLUSTER_NET_SELL_THRESHOLD,
    CLUSTER_SELLERS_THRESHOLD,
    SIGNAL_FADE_DAYS,
    compute_insider_sell_metrics,
)


def _ev(days_ago: int, holder: str, in_out: str, vol: float) -> dict:
    d = (date.today() - timedelta(days=days_ago)).strftime("%Y%m%d")
    return {
        "ann_date": d,
        "trade_date": d,
        "holder_name": holder,
        "holder_type": "G",
        "in_out": in_out,
        "change_vol_shares": vol,
    }


def test_compute_insider_cluster_escape():
    ff = 100_000_000.0
    events = [
        _ev(10, "高管A", "OUT", 500_000),
        _ev(8, "高管B", "OUT", 400_000),
        _ev(5, "高管C", "OUT", 300_000),
        _ev(3, "高管D", "IN", 100_000),
    ]
    m = compute_insider_sell_metrics({"events": events, "free_float_shares": ff})
    assert m["value"] == pytest.approx(1.1, abs=0.01)
    assert m["raw_metrics"]["unique_sellers_count"] == 3
    assert m["raw_metrics"]["cluster_escape_triggered"] is True
    assert m["raw_metrics"]["threat_urgency"] == "HIGH_CLUSTER"
    assert "高紧迫度" in m["fact_statement"]
    node = build_insider_sell_actual_node(m)
    assert node["indicator_name"] == "核心内部人90日实际净减持当量"


def test_compute_insider_signal_fade_70d():
    """002837 类场景：90 日窗口仍有统计值，但最近卖出 >30 天须 LOW_FADED。"""
    ff = 755_555_555.0
    events = [_ev(70, "高管A", "OUT", 2_040_000)]
    m = compute_insider_sell_metrics({"events": events, "free_float_shares": ff})
    assert m["value"] == pytest.approx(0.27, abs=0.01)
    rm = m["raw_metrics"]
    assert rm["days_since_last_sale"] == 70
    assert rm["threat_urgency"] == "LOW_FADED"
    assert rm["signal_decay_applied"] is True
    assert rm["signal_fade_days_threshold"] == SIGNAL_FADE_DAYS
    assert "强制降级警报" in m["fact_statement"]
    assert "70 天前" in m["fact_statement"]
    assert rm["cluster_escape_triggered"] is False


def test_compute_insider_zero_events():
    m = compute_insider_sell_metrics({"events": [], "free_float_shares": 50_000_000.0})
    assert m["value"] == 0.0
    assert m["raw_metrics"]["unique_sellers_count"] == 0
    assert m["raw_metrics"]["threat_urgency"] == "NONE"


def test_missing_free_float_raises():
    with pytest.raises(ValueError, match="free_float"):
        compute_insider_sell_metrics({"events": [], "free_float_shares": None})


def test_render_insider_sell_card():
    from apps.copilot.modules.executing.executing_render import render_insider_sell_actual_card

    m = compute_insider_sell_metrics(
        {
            "events": [
                _ev(2, "A", "OUT", 2_000_000),
                _ev(1, "B", "OUT", 2_000_000),
                _ev(1, "C", "OUT", 2_000_000),
            ],
            "free_float_shares": 100_000_000.0,
        }
    )
    html = render_insider_sell_actual_card(build_insider_sell_actual_node(m))
    assert "insider_sell_actual" in html
    assert "border-left-color:#e11d48" in html
    assert m["raw_metrics"]["cluster_escape_triggered"] or (
        m["value"] >= CLUSTER_NET_SELL_THRESHOLD * 100
        and m["raw_metrics"]["unique_sellers_count"] >= CLUSTER_SELLERS_THRESHOLD
    )


def test_render_insider_faded_visual_cooldown():
    from apps.copilot.modules.executing.executing_render import render_insider_sell_actual_card

    m = compute_insider_sell_metrics(
        {
            "events": [_ev(70, "A", "OUT", 2_040_000)],
            "free_float_shares": 755_555_555.0,
        }
    )
    html = render_insider_sell_actual_card(build_insider_sell_actual_node(m))
    assert "border-left-color:#9ca3af" in html
    assert "信号已衰减" in html
    assert "LOW_FADED" in html
    assert "border-left-color:#e11d48" not in html
