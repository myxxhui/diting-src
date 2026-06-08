"""smart_money_flow T1 算子单测（无需 Tushare Token）。"""
from __future__ import annotations

from apps.copilot.modules.executing.smart_money_flow import compute_smart_money_metrics
from apps.copilot.modules.executing.t1_build import build_telemetry
from datetime import date


def _sample_row(
    *,
    buy_elg=1000.0,
    sell_elg=500.0,
    buy_lg=800.0,
    sell_lg=600.0,
    buy_md=200.0,
    sell_md=300.0,
    buy_sm=100.0,
    sell_sm=150.0,
    trade_date="20260606",
):
    return {
        "trade_date": trade_date,
        "buy_elg_vol": buy_elg,
        "sell_elg_vol": sell_elg,
        "buy_lg_vol": buy_lg,
        "sell_lg_vol": sell_lg,
        "buy_md_vol": buy_md,
        "sell_md_vol": sell_md,
        "buy_sm_vol": buy_sm,
        "sell_sm_vol": sell_sm,
        "net_mf_vol": 0,
    }


def test_compute_smart_money_metrics_outflow():
    payload = {
        "moneyflow_rows": [
            _sample_row(trade_date="20260604"),
            _sample_row(trade_date="20260605"),
            _sample_row(trade_date="20260606", buy_elg=400, sell_elg=900),
        ],
        "free_float_shares": 10_000_000.0,
        "last_update_date": "20260606",
    }
    m = compute_smart_money_metrics(payload)
    # 3日 smart: each day (1000+800)-(500+600)=700 lots; last day (400+800)-(900+600)=-300
    # total lots = 700+700-300 = 1100 lots = 110000 shares
    assert m["value_pct"] == 1.1
    assert "净流入" in m["fact_statement"]
    assert m["raw_metrics"]["3d_smart_money_net_vol"] == 110_000.0


def test_t1_build_smart_money_flow_node():
    raw = {
        "smart_money_flow": {
            "ok": True,
            "source": "Tushare API (moneyflow)",
            "payload": {
                "moneyflow_rows": [
                    _sample_row(trade_date="20260604"),
                    _sample_row(trade_date="20260605"),
                    _sample_row(trade_date="20260606", sell_elg=5000, sell_lg=5000),
                ],
                "free_float_shares": 1_000_000.0,
                "last_update_date": "20260606",
            },
        }
    }
    tel = build_telemetry(
        "601138",
        as_of=date(2026, 6, 9),
        raw_by_key=raw,
        profit_context={},
    )
    sig = tel["portfolio_signals"]["601138.SH"]
    node = sig["indicators"]["smart_money_flow"]
    assert node["value"] is not None
    assert node["indicator_name"] == "L2主力大单资金流向"
    assert "raw_metrics" in node


def test_collect_blocks_without_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_PRO_TOKEN", raising=False)
    from apps.copilot.modules.executing.t0_collectors import _collect_smart_money_flow

    r = _collect_smart_money_flow("601138")
    assert r["ok"] is False
    assert r["probe_key"] == "smart_money_flow"
    assert "TUSHARE_TOKEN" in (r.get("blocker") or "")
