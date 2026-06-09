"""tech_beta_correlation T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.copilot.modules.executing.indicator_nodes import build_tech_beta_correlation_node
from apps.copilot.modules.executing.tech_beta_correlation import (
    _rolling_stats,
    compute_tech_beta_correlation_metrics,
    resolve_sector_index,
)


def _row(day_offset: int, stock_pct: float, index_pct: float) -> dict:
    td = date(2024, 1, 2) + timedelta(days=day_offset)
    return {
        "trade_date": td.strftime("%Y%m%d"),
        "sector_index_code": "931071.CSI",
        "stock_pct_chg": stock_pct / 100.0,
        "index_pct_chg": index_pct / 100.0,
    }


def test_resolve_sector_index_from_profile():
    code, name = resolve_sector_index(
        {"sector_index_code": "931071.CSI", "sector_index_name": "中证人工智能"}
    )
    assert code == "931071.CSI"
    assert name == "中证人工智能"


def test_resolve_sector_index_missing_raises():
    with pytest.raises(ValueError, match="sector_index_code"):
        resolve_sector_index({})


def test_rolling_stats_high_correlation():
    stock = [0.01 * (1 + 0.1 * (i % 5)) for i in range(60)]
    index = [0.008 * (1 + 0.1 * (i % 5)) for i in range(60)]
    r, r2, beta = _rolling_stats(stock, index)
    assert r > 0.9
    assert r2 > 0.8
    assert beta > 0


def test_compute_tech_beta_correlation_metrics_ok():
    rows = [_row(i, 1.0 + (i % 3) * 0.2, 0.8 + (i % 3) * 0.15) for i in range(130)]
    payload = {
        "aligned_rows": rows,
        "rows_in_pg": 130,
        "sector_index_code": "931071.CSI",
        "sector_index_name": "中证人工智能",
    }
    m = compute_tech_beta_correlation_metrics(payload)
    assert -1 <= m["value"] <= 1
    assert m["raw_metrics"]["lookback_window"] == 60
    assert m["raw_metrics"]["beta_coefficient"] is not None
    assert "R-squared" in m["fact_statement"]
    node = build_tech_beta_correlation_node(m)
    assert node["indicator_name"] == "板块Beta共振度与解释系数"


def test_compute_tech_beta_correlation_insufficient_rows():
    payload = {"aligned_rows": [_row(i, 1.0, 0.8) for i in range(50)]}
    with pytest.raises(ValueError, match="不足"):
        compute_tech_beta_correlation_metrics(payload)


def test_render_tech_beta_correlation_card():
    from apps.copilot.modules.executing.executing_render import render_tech_beta_correlation_card

    node = build_tech_beta_correlation_node(
        {
            "value": 0.82,
            "fact_statement": "测试板块 Beta",
            "calculation_logic": "PearsonCorr(标的近60日收益率, 指数近60日收益率)",
            "source": "Tushare Pro Index/Daily",
            "raw_metrics": {
                "lookback_window": 60,
                "pearson_r": 0.821,
                "r_squared": 0.672,
                "beta_coefficient": 1.35,
                "sector_index_used": "931071.CSI",
                "sector_index_name": "中证人工智能",
                "alpha_deviation_today": 0.012,
            },
        }
    )
    html = render_tech_beta_correlation_card(node)
    assert "tech_beta_correlation" in html
    assert "0.82" in html
    assert "板块Beta共振度与解释系数" in html
