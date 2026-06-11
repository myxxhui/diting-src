"""Opus T2 · 可选雷达九维模板注入。"""
from __future__ import annotations

from apps.copilot.modules.executing.t2_preexec_envelope import build_t2_preexec_envelope
from apps.copilot.modules.executing.t2_radar_nine_dim import (
    inject_radar_nine_dim_into_envelope,
)
from apps.copilot.modules.radar.schema import DIM_KEYS


def _minimal_t1() -> dict:
    return {
        "batch_meta": {"system_status": "Nominal"},
        "portfolio_signals": {
            "601138.SH": {
                "stock_name": "工业富联",
                "indicators": {},
            }
        },
    }


def test_inject_radar_nine_dim_disabled():
    env = build_t2_preexec_envelope(_minimal_t1())
    out = inject_radar_nine_dim_into_envelope(env, enabled=False)
    assert out["radar_nine_dim"]["enabled"] is False
    assert any("禁止" in r for r in out["output_contract"]["rules"])
    audit = out["output_contract"]["example"]["symbol_audits"]["601138.SH"]
    assert "radar_nine_dimensions" not in audit


def test_inject_radar_nine_dim_enabled():
    env = build_t2_preexec_envelope(_minimal_t1())
    out = inject_radar_nine_dim_into_envelope(env, enabled=True)
    assert out["radar_nine_dim"]["enabled"] is True
    assert set(out["radar_nine_dim"]["dim_keys"]) == set(DIM_KEYS)
    assert "雷达九维深度研报" in out["system_prompt"]
    audit = out["output_contract"]["example"]["symbol_audits"]["601138.SH"]
    radar = audit["radar_nine_dimensions"]
    assert set(radar["dimensions"].keys()) == set(DIM_KEYS)
    assert any(q["id"] == "radar_nine_dimensions" for q in out["qa_index"])
