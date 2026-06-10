"""T2 JSON 解析与执行区摘要单测。"""
from __future__ import annotations

from apps.copilot.modules.executing.t2_advice_summary import (
    extract_symbol_advice,
    structured_audit_from_payload,
)
from apps.copilot.modules.executing.t2_analyst import _parse_opus_audit_json
from apps.copilot.modules.executing.t2_analyst_render import render_t2_assistant_card


def test_parse_opus_audit_json_trailing_extra_brace():
    inner = '{"Execution_Command":{"action":"hold"},"symbol_audits":{"300502.SZ":{"near_term_advice":"hold"}}}'
    broken = inner + "}"
    parsed = _parse_opus_audit_json(broken)
    assert parsed["Execution_Command"]["action"] == "hold"
    assert "300502.SZ" in parsed["symbol_audits"]


def test_parse_opus_audit_json_markdown_fence():
    raw = '```json\n{"Execution_Command":{"action":"watch"}}\n```'
    parsed = _parse_opus_audit_json(raw)
    assert parsed["Execution_Command"]["action"] == "watch"


def test_structured_audit_reparse_from_raw_text():
    payload = {
        "opus_audit": {"raw_text": "ignored"},
        "opus_raw_text": (
            '{"Execution_Command":{"action":"hold","one_sentence_summary":"测试"},'
            '"symbol_audits":{"601138.SH":{"near_term_advice":"hold","holding_honesty":"维持"}}}}'
        ),
        "api_connected": True,
        "opus_meta": {"tokens_out": 100, "model": "claude-opus-4-8"},
    }
    audit = structured_audit_from_payload(payload)
    assert audit["Execution_Command"]["action"] == "hold"
    html = render_t2_assistant_card(payload, {"status": "ok"})
    assert "组合结论" in html
    assert "持有" in html


def test_extract_symbol_advice():
    payload = {
        "opus_audit": {
            "Execution_Command": {
                "action": "hold",
                "one_sentence_summary": "新易盛观望",
                "targets": [{"symbol": "300502.SZ", "advice": "hold", "rationale": "JL4缺失"}],
            },
            "symbol_audits": {
                "300502.SZ": {
                    "near_term_advice": "hold",
                    "holding_honesty": "维持100股",
                    "cross_validation": "JL1-JL3健康",
                }
            },
        }
    }
    adv = extract_symbol_advice(payload, "300502.SZ", request_id="abc")
    assert adv
    assert adv["action_label"] == "持有"
    assert "新易盛" in adv["summary"]
    assert adv["core_eval"] == "JL1-JL3健康"
