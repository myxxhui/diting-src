"""T1 算子注册表 · 17 项全量。

[Ref: 27_ §3.2~§3.7]
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.copilot.modules.radar.t1.operators.consensus_ops import (
    op_t12_eps_growth,
    op_t13_rating_surge,
)
from apps.copilot.modules.radar.t1.operators.ecosystem_ops import (
    op_t04_profile_llm,
    op_t05_segment_top3,
    op_t06_supply_chain,
    op_t07_peer_rank,
)
from apps.copilot.modules.radar.t1.operators.global_ops import (
    op_t01_market_temperature,
    op_t02_sector_momentum,
    op_t03_sector_flow,
)
from apps.copilot.modules.radar.t1.operators.micro_ops import (
    op_t08_price_action,
    op_t09_northbound,
    op_t10_margin_roc,
    op_t11_dragon_tiger,
)
from apps.copilot.modules.radar.t1.operators.risk_ops import (
    op_t14_financial_red,
    op_t15_pledge,
    op_t16_unlock,
    op_t17_regulatory_llm,
)
from apps.copilot.modules.radar.t1.operators.types import OpResult

OpFn = Callable[..., OpResult]

MICRO_OPERATORS: tuple[OpFn, ...] = (
    op_t08_price_action,
    op_t09_northbound,
    op_t10_margin_roc,
    op_t11_dragon_tiger,
)

ALL_OPERATORS: tuple[OpFn, ...] = (
    op_t01_market_temperature,
    op_t02_sector_momentum,
    op_t03_sector_flow,
    op_t04_profile_llm,
    op_t05_segment_top3,
    op_t06_supply_chain,
    op_t07_peer_rank,
    op_t08_price_action,
    op_t09_northbound,
    op_t10_margin_roc,
    op_t11_dragon_tiger,
    op_t12_eps_growth,
    op_t13_rating_surge,
    op_t14_financial_red,
    op_t15_pledge,
    op_t16_unlock,
    op_t17_regulatory_llm,
)

MICRO_OP_IDS = frozenset({8, 9, 10, 11})


def run_operator(op_fn: OpFn, t0_raw: dict[str, Any]) -> OpResult:
    micro = t0_raw.get("micro") or {}
    if op_fn in MICRO_OPERATORS:
        return op_fn(t0_raw, micro)
    return op_fn(t0_raw)
