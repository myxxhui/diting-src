"""探针注册表 · #15~#24 统一分发。

[Ref: 28_ §4.4 · probes 架构]
"""
from __future__ import annotations

from apps.copilot.modules.executing.probe_keys import OPTIONAL_EVENT_PROBE_KEYS, PROBE_KEYS
from apps.copilot.modules.executing.probes._base import ExecutingProbe, T1LiveContext
from apps.copilot.modules.executing.probes import block_trade_discount as block_trade_discount_mod
from apps.copilot.modules.executing.probes import etf_redemption_impact as etf_redemption_impact_mod
from apps.copilot.modules.executing.probes import insider_sell_actual as insider_sell_actual_mod
from apps.copilot.modules.executing.probes import level2_super_order as level2_super_order_mod
from apps.copilot.modules.executing.probes import margin_short_skew as margin_short_skew_mod
from apps.copilot.modules.executing.probes import qmt_atr_trailing as qmt_atr_trailing_mod
from apps.copilot.modules.executing.probes import retail_concentration as retail_concentration_mod
from apps.copilot.modules.executing.probes import smart_money_flow as smart_money_flow_mod
from apps.copilot.modules.executing.probes import turnover_acceleration as turnover_acceleration_mod
from apps.copilot.modules.executing.probes import volume_price_div as volume_price_div_mod

_PROBE_MODULES: tuple[ExecutingProbe, ...] = (
    qmt_atr_trailing_mod.PROBE,
    volume_price_div_mod.PROBE,
    smart_money_flow_mod.PROBE,
    level2_super_order_mod.PROBE,
    margin_short_skew_mod.PROBE,
    turnover_acceleration_mod.PROBE,
    block_trade_discount_mod.PROBE,
    retail_concentration_mod.PROBE,
    insider_sell_actual_mod.PROBE,
    etf_redemption_impact_mod.PROBE,
)

PROBE_REGISTRY: dict[str, ExecutingProbe] = {p.spec.key: p for p in _PROBE_MODULES}

# 与 probe_keys.PROBE_KEYS 校验一致
_REGISTERED_KEYS = tuple(p.spec.key for p in sorted(_PROBE_MODULES, key=lambda x: x.spec.seq))
if _REGISTERED_KEYS != PROBE_KEYS:
    raise RuntimeError(f"probe_registry 与 probe_keys 不一致: {_REGISTERED_KEYS} vs {PROBE_KEYS}")

REGISTERED_PROBE_KEYS: tuple[str, ...] = PROBE_KEYS

OPTIONAL_SILENT_PROBE_KEYS: frozenset[str] = OPTIONAL_EVENT_PROBE_KEYS


def get_probe(key: str) -> ExecutingProbe:
    probe = PROBE_REGISTRY.get(key)
    if probe is None:
        raise KeyError(f"未注册探针: {key}")
    return probe


def probes_for_keys(keys: tuple[str, ...] | list[str]) -> list[ExecutingProbe]:
    return [get_probe(k) for k in keys]


async def collect_t1_live_for_key(key: str, ctx: T1LiveContext):
    return await get_probe(key).collect_t1_live(ctx)
