"""#20 turnover_acceleration · 探针模块。

[Ref: 28_ §3.2 #20]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_turnover_acceleration_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot
from apps.copilot.modules.executing.turnover_acceleration import (
    SOURCE_TURNOVER,
    compute_turnover_acceleration_metrics,
    load_turnover_acceleration_payload,
)

SPEC = ProbeSpec(
    key="turnover_acceleration",
    seq=20,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-turnover-accel-eod",
    context_group="daily_basic",
)


class TurnoverAccelerationProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_turnover_acceleration_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if payload is None:
            snap = await load_t1_snapshot(ctx.session, sym, "turnover_acceleration")
            if snap:
                return "turnover_acceleration", snap
            raw = ctx.raw_by_key.get("turnover_acceleration")
            raise ValueError(raw.get("blocker") if raw else "turnover_acceleration 未采集")

        metrics = compute_turnover_acceleration_metrics(payload)
        node = build_turnover_acceleration_node(metrics, source=SOURCE_TURNOVER)
        return "turnover_acceleration", node


PROBE = TurnoverAccelerationProbe()
