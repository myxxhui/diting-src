"""margin_short_skew T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.copilot.modules.executing.indicator_nodes import build_margin_short_skew_node
from apps.copilot.modules.executing.level2_super_order import percentile_rank
from apps.copilot.modules.executing.margin_short_skew import compute_margin_short_skew_metrics


def _margin_row(day_offset: int, ratio: float, rzye: float = 1e9) -> dict:
    td = date(2024, 1, 2) + timedelta(days=day_offset)
    trade_date = td.strftime("%Y%m%d")
    return {
        "trade_date": trade_date,
        "rzye": rzye,
        "rqye": 1e7,
        "rzmre": 1e8,
        "margin_short_ratio": rzye / 1e7,
        "free_float_mkt_cap": rzye / ratio if ratio > 0 else None,
        "margin_to_float_ratio": ratio,
    }


def test_percentile_rank_margin_series():
    series = [0.01 + i * 0.001 for i in range(250)]
    assert percentile_rank(series[-1], series) >= 99.0
    assert percentile_rank(series[0], series) <= 1.0


def test_compute_margin_short_skew_extreme_high():
    rows = [_margin_row(i, 0.02 + i * 0.0001) for i in range(249)]
    rows.append(_margin_row(249, 0.12, rzye=2.5e9))
    payload = {
        "margin_rows": rows,
        "rows_in_pg": 250,
        "inferred_trade_date": rows[-1]["trade_date"],
        "settlement_lag_days": 1,
    }
    m = compute_margin_short_skew_metrics(payload)
    assert m["value"] >= 95.0
    assert m["raw_metrics"]["margin_to_float_ratio"] == 0.12
    assert "分位" in m["fact_statement"]
    node = build_margin_short_skew_node(m)
    assert node["indicator_name"] == "两融杠杆倾斜度历史分位"
    assert node["value"] == m["value"]


def test_compute_margin_insufficient_rows():
    payload = {"margin_rows": [_margin_row(0, 0.05)] * 10}
    with pytest.raises(ValueError, match="不足"):
        compute_margin_short_skew_metrics(payload)


def test_render_margin_short_skew_card():
    from apps.copilot.modules.executing.executing_render import render_margin_short_skew_card

    node = build_margin_short_skew_node(
        {
            "value": 99.2,
            "fact_statement": "测试两融陈述",
            "calculation_logic": "PercentileRank(...)",
            "source": "Tushare Margin Detail (T+1 Lag)",
            "raw_metrics": {
                "inferred_trade_date": "2026-06-08",
                "margin_balance": 2_540_000_000.0,
                "margin_to_float_ratio": 0.084,
                "settlement_lag_days": 1,
            },
        }
    )
    html = render_margin_short_skew_card(node)
    assert "margin_short_skew" in html
    assert "99.2" in html
    assert "两融杠杆倾斜度历史分位" in html
