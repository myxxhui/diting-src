"""#18 level2_super_order · 探针模块。

[Ref: 28_ §3.2 #18]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_level2_super_order_node
from apps.copilot.modules.executing.level2_super_order import (
    SOURCE_ELG,
    compute_level2_super_order_metrics,
    load_level2_super_order_payload,
)
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot

SPEC = ProbeSpec(
    key="level2_super_order",
    seq=18,
    matrix="L4_Game",
    cadence="daily",
    job_id="l2-super-order-eod",
    context_group="moneyflow",
)


class Level2SuperOrderProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_level2_super_order_payload(ctx.session, sym)
        if payload is None:
            snap = await load_t1_snapshot(ctx.session, sym, "level2_super_order")
            if snap:
                return "level2_super_order", snap
            raw = ctx.raw_by_key.get("level2_super_order")
            raise ValueError(raw.get("blocker") if raw else "level2_super_order 未采集")

        metrics = compute_level2_super_order_metrics(payload)
        node = build_level2_super_order_node(metrics, source=SOURCE_ELG)
        return "level2_super_order", node


PROBE = Level2SuperOrderProbe()
