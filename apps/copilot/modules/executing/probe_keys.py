"""探针启用列表（无依赖 · 打破 profile/registry/storage 循环导入）。

[Ref: 28_ §4.5]
"""
from __future__ import annotations

# 权威启用列表（#15~#25 · seq 序）
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
    "tech_beta_correlation",
)

OPTIONAL_EVENT_PROBE_KEYS: frozenset[str] = frozenset(
    {"block_trade_discount", "etf_redemption_impact"}
)

L3_KEYS: tuple[str, ...] = (
    "fii_twse_cloud",
    "fii_odm_direct_ratio",
    "fii_gb200_milestone",
)
L4_KEYS: tuple[str, ...] = PROBE_KEYS

# JL4 持仓依赖：仅 #1 须 user_positions.opened_at（峰值窗）；其余 #2~#11 待建仓即可采集跟踪
JL4_POSITION_DEPENDENT_KEYS: frozenset[str] = frozenset({"qmt_atr_trailing"})
JL4_POSITION_INDEPENDENT_KEYS: tuple[str, ...] = tuple(
    k for k in PROBE_KEYS if k not in JL4_POSITION_DEPENDENT_KEYS
)
