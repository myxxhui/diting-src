"""turnover_acceleration T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.copilot.modules.executing.indicator_nodes import build_turnover_acceleration_node
from apps.copilot.modules.executing.turnover_acceleration import compute_turnover_acceleration_metrics


def _row(day_offset: int, rate_pct: float, vol_ratio: float = 1.0) -> dict:
    td = date(2024, 1, 2) + timedelta(days=day_offset)
    return {
        "trade_date": td.strftime("%Y%m%d"),
        "turnover_rate_f": rate_pct / 100.0,
        "volume_ratio": vol_ratio,
    }


def test_compute_turnover_acceleration_spike():
    rows = [_row(i, 5.0) for i in range(139)]
    rows.append(_row(139, 16.25, 2.85))
    payload = {"turnover_rows": rows, "rows_in_pg": 140}
    m = compute_turnover_acceleration_metrics(payload)
    assert m["value"] >= 3.0
    assert m["raw_metrics"]["current_turnover_f"] == pytest.approx(0.1625)
    assert m["raw_metrics"]["20d_mean_turnover_f"] == pytest.approx(0.05)
    assert m["raw_metrics"]["120d_accel_percentile"] >= 90
    assert "3." in m["fact_statement"] or m["value"] >= 3
    node = build_turnover_acceleration_node(m)
    assert node["indicator_name"] == "自由换手率异动倍数"


def test_compute_turnover_insufficient_rows():
    payload = {"turnover_rows": [_row(i, 5.0) for i in range(50)]}
    with pytest.raises(ValueError, match="不足"):
        compute_turnover_acceleration_metrics(payload)


def test_render_turnover_acceleration_card():
    from apps.copilot.modules.executing.executing_render import render_turnover_acceleration_card

    node = build_turnover_acceleration_node(
        {
            "value": 3.25,
            "fact_statement": "测试换手加速",
            "calculation_logic": "今日 turnover_rate_f / 过去20日平均",
            "source": "Tushare Daily Basic (turnover_rate_f)",
            "raw_metrics": {
                "current_turnover_f": 0.1625,
                "20d_mean_turnover_f": 0.05,
                "120d_accel_percentile": 96.5,
                "volume_ratio": 2.85,
            },
        }
    )
    html = render_turnover_acceleration_card(node)
    assert "turnover_acceleration" in html
    assert "3.25" in html
    assert "自由换手率异动倍数" in html
