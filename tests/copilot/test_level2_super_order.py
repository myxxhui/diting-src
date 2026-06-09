"""level2_super_order T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.indicator_nodes import build_level2_super_order_node
from apps.copilot.modules.executing.level2_super_order import (
    compute_level2_super_order_metrics,
    net_elg_amount_yuan,
    percentile_rank,
)


def _elg_row(trade_date: str, net_wan: float) -> dict:
    half = abs(net_wan) / 2
    buy = half if net_wan >= 0 else 0.0
    sell = half if net_wan < 0 else 0.0
    if net_wan >= 0:
        buy = net_wan
        sell = 0.0
    else:
        buy = 0.0
        sell = -net_wan
    return {
        "trade_date": trade_date,
        "buy_elg_vol": 100.0,
        "sell_elg_vol": 50.0,
        "buy_elg_amount": buy,
        "sell_elg_amount": sell,
        "net_elg_amount": net_wan,
    }


def test_percentile_rank_extreme_high():
    series = [float(i) for i in range(120)]
    assert percentile_rank(119.0, series) >= 99.0
    assert percentile_rank(0.0, series) <= 1.0


def test_net_elg_amount_yuan():
    row = {"buy_elg_amount": 4250.0, "sell_elg_amount": 0.0}
    assert net_elg_amount_yuan(row) == 42_500_000.0


def test_compute_level2_super_order_metrics_spike():
    rows = [_elg_row(f"202501{i:02d}", float(i)) for i in range(1, 120)]
    rows.append(_elg_row("20250501", 5000.0))
    payload = {"moneyflow_rows": rows, "rows_in_pg": 120, "last_update_date": "20250501"}
    m = compute_level2_super_order_metrics(payload)
    assert m["value"] >= 95.0
    assert m["raw_metrics"]["current_net_elg_amount"] == 50_000_000.0
    assert "98" in m["fact_statement"] or m["value"] >= 95
    node = build_level2_super_order_node(m)
    assert node["indicator_name"] == "L2特大单净动能历史分位"
    assert node["value"] == m["value"]


def test_compute_insufficient_rows():
    payload = {"moneyflow_rows": [_elg_row("20250101", 1.0)] * 10}
    with pytest.raises(ValueError, match="不足"):
        compute_level2_super_order_metrics(payload)


def test_render_level2_super_order_card():
    from apps.copilot.modules.executing.executing_render import render_level2_super_order_card

    node = build_level2_super_order_node(
        {
            "value": 98.5,
            "fact_statement": "测试陈述",
            "calculation_logic": "PercentileRank(...)",
            "source": "Tushare L2 Moneyflow (elg_amount)",
            "raw_metrics": {
                "current_net_elg_amount": 42_500_000.0,
                "lookback_window_days": 120,
            },
        }
    )
    html = render_level2_super_order_card(node)
    assert "level2_super_order" in html
    assert "98.5" in html
    assert "L2特大单净动能历史分位" in html
