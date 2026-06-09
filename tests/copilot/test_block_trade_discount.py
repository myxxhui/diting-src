"""block_trade_discount T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.block_trade_discount import (
    IMPACT_SILENT_THRESHOLD,
    compute_block_trade_discount_metrics,
)
from apps.copilot.modules.executing.indicator_nodes import build_block_trade_discount_node


def _payload(
    *,
    discount: float = -0.1124,
    impact: float = 0.0215,
    amount: float = 156_000_000.0,
    mv: float = 7_250_000_000.0,
    hist: list[float] | None = None,
) -> dict:
    rows = []
    for i, d in enumerate(hist or [-0.05, -0.03]):
        rows.append(
            {
                "trade_date": f"20260{i+1}01",
                "vwap_discount_rate": d,
                "float_impact_ratio": 0.002,
                "total_amount_yuan": 1e7,
                "free_float_mv_yuan": mv,
                "trades_count": 1,
            }
        )
    rows.append(
        {
            "trade_date": "20260608",
            "vwap_discount_rate": discount,
            "float_impact_ratio": impact,
            "total_amount_yuan": amount,
            "free_float_mv_yuan": mv,
            "trades_count": 3,
            "vwap_price": 10.0,
            "close_price": 11.26,
        }
    )
    return {"block_trade_rows": rows}


def test_compute_block_trade_discount_material():
    m = compute_block_trade_discount_metrics(_payload())
    assert m is not None
    assert m["value"] == pytest.approx(-11.24, abs=0.01)
    assert m["raw_metrics"]["float_impact_ratio"] == pytest.approx(0.0215)
    assert m["raw_metrics"]["trades_count"] == 3
    node = build_block_trade_discount_node(m)
    assert node["indicator_name"] == "大宗交易加权折价与盘口冲击"


def test_compute_block_trade_silent_filter():
    m = compute_block_trade_discount_metrics(_payload(impact=IMPACT_SILENT_THRESHOLD * 0.5))
    assert m is None


def test_compute_block_trade_no_rows():
    assert compute_block_trade_discount_metrics({"block_trade_rows": []}) is None


def test_render_block_trade_discount_card():
    from apps.copilot.modules.executing.executing_render import render_block_trade_discount_card

    node = build_block_trade_discount_node(
        compute_block_trade_discount_metrics(_payload()) or {}
    )
    html = render_block_trade_discount_card(node)
    assert "block_trade_discount" in html
    assert "border-l-indigo-500" in html


def test_describe_block_trade_ui_state_silent():
    from apps.copilot.modules.executing.block_trade_discount import describe_block_trade_ui_state

    st = describe_block_trade_ui_state(_payload(impact=0.0005))
    assert st["mode"] == "silent"
    assert "0.1%" in st["message"]


def test_render_block_trade_silent_card():
    from apps.copilot.modules.executing.block_trade_discount import describe_block_trade_ui_state
    from apps.copilot.modules.executing.executing_render import render_block_trade_silent_card

    st = describe_block_trade_ui_state(_payload(impact=0.0005))
    html = render_block_trade_silent_card(st)
    assert "block_trade_discount" in html
    assert "静默" in html
    assert "事件驱动" in html
