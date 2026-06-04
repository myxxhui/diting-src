"""T1 DeepSeek / 规则路由单测。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.radar.context_matrix import build_context_matrix
from apps.copilot.modules.radar.model_router import radar_t1_uses_deepseek, t1_step_label
from apps.copilot.modules.radar.t1_distill import _parse_matrix_json

SAMPLE_T0 = {
    "symbol": "601138",
    "name": "工业富联",
    "quote": {"status": "ok", "last_close": 10.0},
    "profile": {"status": "ok", "name": "工业富联", "industry": "电子"},
    "financials": {"status": "error", "detail": "x"},
    "valuation": {"status": "ok", "pe_ttm": 12},
}


def test_t1_step_label_rule(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("RADAR_T1_MODE", "rule")
    assert "规则" in t1_step_label()
    assert not radar_t1_uses_deepseek()


def test_t1_step_label_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("RADAR_T1_MODE", "auto")
    assert "DeepSeek" in t1_step_label()
    assert radar_t1_uses_deepseek()


def test_parse_matrix_json_codeblock():
    raw = '说明\n```json\n{"matrix": {"行情": {}}, "unavailable": []}\n```'
    p = _parse_matrix_json(raw)
    assert "matrix" in p


@pytest.mark.asyncio
async def test_build_t1_payload_rule_fallback(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("RADAR_T1_MODE", "rule")
    from apps.copilot.modules.radar.t1_distill import build_t1_payload

    out = await build_t1_payload(SAMPLE_T0)
    rule = build_context_matrix(SAMPLE_T0)
    assert out["t1_fallback"] == "rule"
    assert out["fact_count"] == rule["fact_count"]
