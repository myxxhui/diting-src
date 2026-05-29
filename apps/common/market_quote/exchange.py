"""A 股交易所前缀解析。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §三]
"""
from __future__ import annotations

from typing import Literal


def validate_symbol(symbol: str) -> str:
    sym = str(symbol).strip()
    if len(sym) != 6 or not sym.isdigit():
        raise ValueError(f"symbol 须为 6 位数字: {symbol!r}")
    return sym


def _resolve_exchange(symbol: str) -> Literal["sh", "sz"]:
    """沪市 sh / 深市 sz。"""
    sym = validate_symbol(symbol)
    if sym.startswith(("60", "68", "5")):
        return "sh"
    if sym.startswith(("00", "30")):
        return "sz"
    raise ValueError(f"无法识别交易所: {symbol}")


def _em_prefix(symbol: str) -> Literal["0", "1"]:
    """东方财富 secid 前缀：沪市 1 / 深市 0。"""
    ex = _resolve_exchange(symbol)
    return "1" if ex == "sh" else "0"


def tencent_code(symbol: str) -> str:
    return f"{_resolve_exchange(symbol)}{validate_symbol(symbol)}"


def eastmoney_secid(symbol: str) -> str:
    return f"{_em_prefix(symbol)}.{validate_symbol(symbol)}"
