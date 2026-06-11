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


def test_parse_opus_audit_json_missing_closing_braces():
    """Opus end_turn 但少闭合括号（生产 48203e13 类故障）。"""
    inner = (
        '{"Executing_Daily_Audit":{"L3_Fundamental_Verdict":"测试"},'
        '"Execution_Command":{"action":"trim_30_pct","one_sentence_summary":"摘要",'
        '"stop_loss_line":"止损线","targets":[{"symbol":"300502.SZ","advice":"trim"}]},'
        '"symbol_audits":{"300502.SZ":{"near_term_advice":"trim"}}'
    )
    broken = inner + "}}"  # 缺 1 个 }
    parsed = _parse_opus_audit_json(broken)
    assert parsed["Execution_Command"]["action"] == "trim_30_pct"
    assert "300502.SZ" in parsed["symbol_audits"]


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
    assert adv["summary"] == "JL4缺失"
    assert "新易盛观望" not in adv["summary"]
    assert adv["core_eval"] == "JL1-JL3健康"
    assert adv["operation_hint"] == "维持100股"


def test_extract_symbol_advice_rejects_portfolio_only():
    payload = {
        "opus_audit": {
            "Execution_Command": {
                "action": "hold",
                "one_sentence_summary": "组合整体持有，工业富联与新易盛均观望",
                "targets": [],
            },
            "Reasoning_Engine": {"cross_validation_logic": "组合级推理链"},
            "symbol_audits": {},
        }
    }
    assert extract_symbol_advice(payload, "300502.SZ") is None


def test_extract_symbol_advice_no_portfolio_cross_fallback():
    payload = {
        "opus_audit": {
            "Execution_Command": {
                "action": "hold",
                "one_sentence_summary": "组合广意",
                "targets": [{"symbol": "601138.SH", "advice": "hold", "rationale": "FII逻辑完好"}],
            },
            "Reasoning_Engine": {"cross_validation_logic": "五龙组合推理"},
            "symbol_audits": {
                "601138.SH": {"near_term_advice": "hold"},
            },
        }
    }
    adv = extract_symbol_advice(payload, "601138.SH")
    assert adv
    assert adv["summary"] == "FII逻辑完好"
    assert adv["core_eval"] == ""
    assert "五龙组合" not in (adv.get("core_eval") or "")
