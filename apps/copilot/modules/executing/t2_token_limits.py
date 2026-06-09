"""T2 持仓分析 · Opus 输入/输出 token 上限配置。

[Ref: 28_ §5]
"""
from __future__ import annotations

import os
from typing import Any

# Opus 4.6 单次输出上限（Anthropic API）
ABSOLUTE_MAX_OUTPUT_TOKENS = 32_000
# 输入字符上限（约 4 字符/token · 对齐 200k 上下文余量）
ABSOLUTE_MAX_INPUT_CHARS = 400_000

DEFAULT_MAX_OUTPUT_TOKENS = 16_384
DEFAULT_MAX_INPUT_CHARS = 180_000


def t2_max_output_tokens() -> int:
    raw = os.getenv("EXECUTING_T2_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
    try:
        val = int(raw)
    except ValueError:
        val = DEFAULT_MAX_OUTPUT_TOKENS
    return min(max(1024, val), ABSOLUTE_MAX_OUTPUT_TOKENS)


def t2_max_input_chars() -> int:
    raw = os.getenv("EXECUTING_T2_MAX_INPUT_CHARS", str(DEFAULT_MAX_INPUT_CHARS))
    try:
        val = int(raw)
    except ValueError:
        val = DEFAULT_MAX_INPUT_CHARS
    return min(max(10_000, val), ABSOLUTE_MAX_INPUT_CHARS)


def estimate_opus_input_chars(messages: list[dict[str, str]]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def validate_t2_opus_messages(messages: list[dict[str, str]]) -> dict[str, Any]:
    """校验输入规模；超限抛 ValueError。"""
    chars = estimate_opus_input_chars(messages)
    max_in = t2_max_input_chars()
    if chars > max_in:
        raise ValueError(
            f"T2 输入过大：{chars:,} 字符，上限 {max_in:,}（EXECUTING_T2_MAX_INPUT_CHARS）"
        )
    return {
        "input_chars": chars,
        "max_input_chars": max_in,
        "max_output_tokens": t2_max_output_tokens(),
    }


def token_limits_summary() -> dict[str, int]:
    return {
        "max_output_tokens": t2_max_output_tokens(),
        "max_input_chars": t2_max_input_chars(),
        "absolute_max_output_tokens": ABSOLUTE_MAX_OUTPUT_TOKENS,
        "absolute_max_input_chars": ABSOLUTE_MAX_INPUT_CHARS,
    }
