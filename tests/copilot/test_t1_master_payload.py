"""T1 批量 portfolio_signals 结构单测。

[Ref: 28_ §4.1]
"""
from __future__ import annotations

from datetime import date

from apps.copilot.modules.executing.t1_build import (
    build_telemetry,
    extract_stock_indicators,
    stock_signal_from_legacy_telemetry,
    telemetry_probe_stats,
)


def test_batch_payload_shape_no_fabrication():
    raw = {
        "qmt_atr_trailing": {
            "ok": True,
            "source": "PG + Redis",
            "payload": {
                "indicator_key": "qmt_atr_trailing",
                "value": 2.35,
                "calculation_logic": "(peak 84.95 - cur 74.06) / ATR 4.64",
                "fact_statement": "已回撤 2.35 倍 ATR。",
            },
        },
    }
    tel = build_telemetry(
        "601138",
        as_of=date(2026, 6, 8),
        raw_by_key=raw,
        profit_context={"has_position": False, "name": "工业富联"},
        execution_id="batch_task_20260608_150500",
    )
    assert tel["batch_meta"]["execution_id"] == "batch_task_20260608_150500"
    assert tel["batch_meta"]["total_stocks_checked"] == 1
    sig = tel["portfolio_signals"]["601138.SH"]
    assert sig["stock_name"] == "工业富联"
    assert "position_context" not in sig
    assert sig["indicators"]["qmt_atr_trailing"]["value"] == 2.35
    assert "degraded_probes" not in sig or not sig["degraded_probes"]

    stats = telemetry_probe_stats(tel)
    assert stats["filled"] == 1
    assert stats["missing"] == []

    ind = extract_stock_indicators(tel, "601138")
    assert "qmt_atr_trailing" in ind


def test_legacy_telemetry_compat():
    legacy = {
        "meta_info": {
            "symbol": "601138.SH",
            "company_name": "工业富联",
            "system_health": {"degraded_probes": ["x"]},
        },
        "L3_business_fundamentals": {},
        "L4_capital_game_microstructure": {
            "qmt_atr_trailing": {"value": 1.1, "source": "t", "calculation_logic": "l", "fact_statement": "f"}
        },
    }
    sig = stock_signal_from_legacy_telemetry(legacy)
    assert sig is not None
    assert sig["indicators"]["qmt_atr_trailing"]["value"] == 1.1
    ind = extract_stock_indicators(legacy, "601138")
    assert ind["qmt_atr_trailing"]["value"] == 1.1
