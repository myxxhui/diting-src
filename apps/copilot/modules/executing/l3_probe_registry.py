"""JL3 探针注册表。

[Ref: 28_ §4.4 · L3_Business]
"""
from __future__ import annotations

from apps.copilot.modules.executing.probe_keys import L3_KEYS
from apps.copilot.modules.executing.probes._base import ExecutingProbe, T1LiveContext
from apps.copilot.modules.executing.probes.l3 import fii_twse_cloud as fii_twse_cloud_mod

_L3_PROBE_MODULES: tuple[ExecutingProbe, ...] = (fii_twse_cloud_mod.PROBE,)

L3_PROBE_REGISTRY: dict[str, ExecutingProbe] = {p.spec.key: p for p in _L3_PROBE_MODULES}

_REGISTERED_L3 = tuple(p.spec.key for p in sorted(_L3_PROBE_MODULES, key=lambda x: x.spec.seq))
if _REGISTERED_L3 != L3_KEYS:
    raise RuntimeError(f"l3_probe_registry 与 L3_KEYS 不一致: {_REGISTERED_L3} vs {L3_KEYS}")


def get_l3_probe(key: str) -> ExecutingProbe:
    probe = L3_PROBE_REGISTRY.get(key)
    if probe is None:
        raise KeyError(f"未注册 JL3 探针: {key}")
    return probe


async def collect_t1_live_l3_for_key(key: str, ctx: T1LiveContext):
    return await get_l3_probe(key).collect_t1_live(ctx)
