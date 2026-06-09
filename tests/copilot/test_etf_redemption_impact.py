"""etf_redemption_impact T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

from apps.copilot.modules.executing.etf_redemption_impact import (
    IMPACT_MATERIAL_THRESHOLD,
    IMPACT_SILENT_THRESHOLD,
    compute_etf_redemption_metrics,
    describe_etf_redemption_ui_state,
)
from apps.copilot.modules.executing.indicator_nodes import build_etf_redemption_impact_node


def _payload(
    *,
    chg: float = -70000.0,
    nav: float = 1.05,
    weight: float = 0.085,
    amount: float = 2_000_000_000.0,
    trade_date: str = "20260608",
) -> dict:
    return {
        "etf_links": [
            {
                "etf_ts_code": "512660.SH",
                "stock_weight": weight,
                "report_end_date": "20250331",
                "link_source": "index_weight:000852.SH",
            }
        ],
        "etf_share_series": {
            "512660.SH": [
                {
                    "trade_date": "20260607",
                    "fd_share": 1369708.0,
                    "fd_share_change": None,
                    "unit_nav": nav,
                },
                {
                    "trade_date": trade_date,
                    "fd_share": 1369708.0 + chg,
                    "fd_share_change": chg,
                    "unit_nav": nav,
                },
            ]
        },
        "stock_amount_by_date": {
            "20260607": amount,
            trade_date: amount,
        },
    }


def test_compute_etf_redemption_material_impact():
    m = compute_etf_redemption_metrics(_payload())
    assert m is not None
    rm = m["raw_metrics"]
    assert rm["threat_urgency"] == "ELEVATED"
    assert rm["top_associated_etf"] == "512660.SH"
    assert m["value"] < 0
    assert abs(rm["impact_ratio"]) >= IMPACT_MATERIAL_THRESHOLD
    assert "穿透" in m["fact_statement"]
    node = build_etf_redemption_impact_node(m)
    assert node["indicator_name"] == "核心ETF被动资金冲击当量"


def test_compute_etf_redemption_silent_filter():
    # 极小赎回 → 冲击 <1%
    tiny = _payload(chg=-0.01, weight=0.001, amount=50_000_000_000.0)
    assert compute_etf_redemption_metrics(tiny) is None


def test_compute_etf_redemption_no_links():
    assert compute_etf_redemption_metrics({"etf_links": []}) is None


def test_describe_etf_redemption_ui_state_silent():
    st = describe_etf_redemption_ui_state(_payload(chg=-0.01, weight=0.001, amount=50_000_000_000.0))
    assert st["mode"] == "silent"
    assert st["reason"] == "impact_below_threshold"


def test_render_etf_redemption_cards():
    from apps.copilot.modules.executing.executing_render import (
        render_etf_redemption_impact_card,
        render_etf_redemption_silent_card,
    )

    m = compute_etf_redemption_metrics(_payload())
    html = render_etf_redemption_impact_card(build_etf_redemption_impact_node(m))
    assert "etf_redemption_impact" in html
    assert "border-left-color:#7c3aed" in html

    st = describe_etf_redemption_ui_state(_payload(chg=-0.01, weight=0.001, amount=50_000_000_000.0))
    silent = render_etf_redemption_silent_card(st)
    assert "静默" in silent
    assert IMPACT_SILENT_THRESHOLD == 0.01
