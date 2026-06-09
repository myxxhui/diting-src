"""#22 retail_concentration · 探针模块。

[Ref: 28_ §3.2 #22]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_retail_concentration_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.retail_concentration import (
    SOURCE_RETAIL,
    compute_retail_concentration_metrics,
    load_retail_concentration_payload,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot

SPEC = ProbeSpec(
    key="retail_concentration",
    seq=22,
    matrix="L4_Game",
    cadence="dynamic",
    job_id="l4-retail-concentration-eod",
    context_group="moneyflow",
)


class RetailConcentrationProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_retail_concentration_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if not payload:
            snap = await load_t1_snapshot(ctx.session, sym, "retail_concentration")
            if snap:
                return "retail_concentration", snap
            raw = ctx.raw_by_key.get("retail_concentration")
            raise ValueError(raw.get("blocker") if raw else "retail_concentration 未采集")

        metrics = compute_retail_concentration_metrics(payload)
        node = build_retail_concentration_node(metrics, source=SOURCE_RETAIL)
        return "retail_concentration", node


PROBE = RetailConcentrationProbe()
