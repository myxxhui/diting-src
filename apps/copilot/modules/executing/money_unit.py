"""执行中工作区 · 统一货币单位（T1 batch_meta 单一事实来源）。

[Ref: 28_ §4.1]
"""
from __future__ import annotations

from typing import Any

EXECUTING_MONEY_UNIT = "人民币"


def attach_money_unit(batch_meta: dict[str, Any]) -> dict[str, Any]:
    """batch_meta 注入统一 money_unit 字符串。"""
    batch_meta["money_unit"] = EXECUTING_MONEY_UNIT
    return batch_meta


def round_price(value: float | int) -> float:
    return round(float(value), 2)


def format_price_display(value: float | int | None) -> str:
    """前端展示：数值 + 元（单位见 batch money_unit）。"""
    if value is None:
        return "—"
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return f"{text}元"


def format_pct_display(value: float | int) -> str:
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return f"{text}%"
