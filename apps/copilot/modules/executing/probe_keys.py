"""探针启用列表（无依赖 · 打破 profile/registry/storage 循环导入）。

[Ref: 28_ §4.5]
"""
from __future__ import annotations

# 权威启用列表（#15~#24 · seq 序）
PROBE_KEYS: tuple[str, ...] = (
    "qmt_atr_trailing",
    "volume_price_div",
    "smart_money_flow",
    "level2_super_order",
    "margin_short_skew",
    "turnover_acceleration",
    "block_trade_discount",
    "retail_concentration",
    "insider_sell_actual",
    "etf_redemption_impact",
)

OPTIONAL_EVENT_PROBE_KEYS: frozenset[str] = frozenset(
    {"block_trade_discount", "etf_redemption_impact"}
)

L3_KEYS: tuple[str, ...] = ()
L4_KEYS: tuple[str, ...] = PROBE_KEYS
