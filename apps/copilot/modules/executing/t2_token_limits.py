"""T2 持仓分析 · Opus 输入/输出 token 上限配置。

[Ref: 28_ §5]
"""
from __future__ import annotations

import json
import os
from typing import Any

# Opus 4.6 单次输出上限（Anthropic API）
ABSOLUTE_MAX_OUTPUT_TOKENS = 32_000
# 输入字符上限（约 4 字符/token · 对齐 200k 上下文余量）
ABSOLUTE_MAX_INPUT_CHARS = 400_000

DEFAULT_MAX_OUTPUT_TOKENS = 32_000
DEFAULT_MAX_INPUT_CHARS = 400_000


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


def format_output_budget_section(*, max_output_tokens: int, symbol_count: int) -> str:
    """Opus system prompt 篇幅硬约束（按配置上限动态生成）。"""
    n = max(1, symbol_count)
    per_answer = max(60, min(180, max_output_tokens // n // 45))
    per_cross = min(280, per_answer * 2)
    return (
        "## 输出篇幅硬约束（违反即不合格）\n"
        f"- API max_output_tokens={max_output_tokens:,}：完整 JSON 必须在此预算内闭合；"
        "禁止触顶截断（stop_reason=max_tokens）\n"
        "- 仅输出一个 JSON 对象，禁止 Markdown 代码围栏、禁止 JSON 前后任何说明文字\n"
        f"- 当前 {n} 只标的：优先保证 Execution_Command、near_term_advice、cross_validation 完整\n"
        f"- checklist 每题 answer ≤{per_answer} 字；cross_validation 每标的 ≤{per_cross} 字\n"
        "- Executing_Daily_Audit 每标的 L3/L4 段各 ≤150 字；holding_honesty ≤120 字\n"
        "- jl4_read.reading 每条 ≤80 字；禁止复述 user_payload 大段原文\n"
        "- 数据点用「口径·时间·来源」紧凑句式，禁止长段落与重复字段"
    )


def inject_t2_output_budget(
    envelope: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    symbol_count: int,
) -> None:
    """将输出 token 硬顶写入 system prompt 与 output_contract.rules。"""
    max_out = t2_max_output_tokens()
    budget = format_output_budget_section(
        max_output_tokens=max_out,
        symbol_count=symbol_count,
    )
    messages[0]["content"] = (messages[0]["content"] or "").rstrip() + "\n\n" + budget

    oc = envelope.setdefault("output_contract", {})
    rules = list(oc.get("rules") or [])
    cap_rule = f"总输出 JSON ≤ {max_out:,} tokens（硬顶，触顶即失败）"
    if not rules or rules[0] != cap_rule:
        rules.insert(0, cap_rule)
    oc["rules"] = rules
    oc["max_output_tokens"] = max_out

    try:
        user_body = json.loads(messages[1]["content"])
    except (json.JSONDecodeError, IndexError, KeyError):
        return
    user_body["output_contract"] = oc
    messages[1]["content"] = json.dumps(user_body, ensure_ascii=False)
