"""执行区持仓生命周期 · 层 A 待建仓 / 层 B 分期开放。

[Ref: 28_ §6.1]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.probe_keys import (
    JL4_POSITION_DEPENDENT_KEYS,
    JL4_POSITION_INDEPENDENT_KEYS,
)

LIFECYCLE_PENDING_BUILD = "pending_build"
LIFECYCLE_HOLDING = "holding"

_LIFECYCLE_ALIASES_HOLDING = frozenset({"holding", "held", "已建仓"})
_LIFECYCLE_ALIASES_PENDING = frozenset({"pending_build", "pending", "待建仓"})


def normalize_lifecycle_mode(value: str | None) -> str:
    """晋级执行区生命周期；未选或未知值 → 待建仓。"""
    v = (value or "").strip().lower()
    if v in _LIFECYCLE_ALIASES_HOLDING:
        return LIFECYCLE_HOLDING
    if v in _LIFECYCLE_ALIASES_PENDING or not v:
        return LIFECYCLE_PENDING_BUILD
    return LIFECYCLE_PENDING_BUILD


def validate_holding_fields(data: dict[str, Any]) -> None:
    """已建仓晋级须同时具备建仓日、成本价、股数。"""
    if not is_holding_complete(data):
        raise ValueError("holding_fields_required")


def is_holding_complete(base: dict[str, Any]) -> bool:
    """层 A 持仓完备：建仓日 + 成本价 + 股数均已填写。"""
    opened = base.get("opened_at")
    cost = float(base.get("cost_price") or 0)
    qty = float(base.get("quantity") or 0)
    return bool(opened and str(opened).strip()) and cost > 0 and qty > 0


def resolve_lifecycle_status(base: dict[str, Any]) -> str:
    """未填层 A 基础数据 → 默认待建仓。"""
    return LIFECYCLE_HOLDING if is_holding_complete(base) else LIFECYCLE_PENDING_BUILD


def is_collect_enrolled(base: dict[str, Any]) -> bool:
    """已加入 executing_collect_symbols 且 enabled。"""
    return bool(base.get("has_base") and base.get("enabled", True))


def filter_l4_for_lifecycle(
    l4: dict[str, Any],
    lifecycle: str,
) -> dict[str, Any]:
    """待建仓时剔除依赖建仓日的 JL4 缓存（禁止旧 ATR 冒充持仓监控）。"""
    if lifecycle == LIFECYCLE_HOLDING:
        return l4
    out = {k: v for k, v in l4.items() if k in JL4_POSITION_INDEPENDENT_KEYS}
    return out


__all__ = [
    "LIFECYCLE_HOLDING",
    "LIFECYCLE_PENDING_BUILD",
    "JL4_POSITION_DEPENDENT_KEYS",
    "JL4_POSITION_INDEPENDENT_KEYS",
    "filter_l4_for_lifecycle",
    "is_collect_enrolled",
    "is_holding_complete",
    "normalize_lifecycle_mode",
    "resolve_lifecycle_status",
    "validate_holding_fields",
]
