"""T2 token 上限单测。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.t2_token_limits import (
    ABSOLUTE_MAX_OUTPUT_TOKENS,
    estimate_opus_input_chars,
    t2_max_input_chars,
    t2_max_output_tokens,
    validate_t2_opus_messages,
)


def test_default_limits(monkeypatch):
    monkeypatch.delenv("EXECUTING_T2_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("EXECUTING_T2_MAX_INPUT_CHARS", raising=False)
    assert t2_max_output_tokens() == 32000
    assert t2_max_input_chars() == 400_000


def test_env_override(monkeypatch):
    monkeypatch.setenv("EXECUTING_T2_MAX_OUTPUT_TOKENS", "20000")
    monkeypatch.setenv("EXECUTING_T2_MAX_INPUT_CHARS", "200000")
    assert t2_max_output_tokens() == 20000
    assert t2_max_input_chars() == 200_000


def test_absolute_cap(monkeypatch):
    monkeypatch.setenv("EXECUTING_T2_MAX_OUTPUT_TOKENS", "999999")
    assert t2_max_output_tokens() == ABSOLUTE_MAX_OUTPUT_TOKENS


def test_validate_input_ok():
    msgs = [{"role": "user", "content": "x" * 1000}]
    stats = validate_t2_opus_messages(msgs)
    assert stats["input_chars"] == 1000
    assert estimate_opus_input_chars(msgs) == 1000


def test_validate_input_too_large(monkeypatch):
    monkeypatch.setenv("EXECUTING_T2_MAX_INPUT_CHARS", "15000")
    with pytest.raises(ValueError, match="T2 输入过大"):
        validate_t2_opus_messages([{"role": "user", "content": "x" * 20_000}])


def test_output_budget_injection(monkeypatch):
    from apps.copilot.modules.executing.t2_token_limits import inject_t2_output_budget

    monkeypatch.delenv("EXECUTING_T2_MAX_OUTPUT_TOKENS", raising=False)
    envelope = {"output_contract": {"rules": ["existing"]}}
    messages = [
        {"role": "system", "content": "base"},
        {"role": "user", "content": '{"output_contract": {"rules": []}}'},
    ]
    inject_t2_output_budget(envelope, messages, symbol_count=3)
    assert "max_output_tokens=32,000" in messages[0]["content"]
    assert envelope["output_contract"]["rules"][0].startswith("总输出 JSON ≤")
    user_body = __import__("json").loads(messages[1]["content"])
    assert user_body["output_contract"]["max_output_tokens"] == 32000
