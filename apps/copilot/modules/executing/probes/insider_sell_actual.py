"""#23 insider_sell_actual · 探针模块。

[Ref: 28_ §3.2 #23]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_insider_sell_actual_node
from apps.copilot.modules.executing.insider_sell_actual import (
    SOURCE_INSIDER,
    compute_insider_sell_metrics,
    load_insider_sell_payload,
)
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot

SPEC = ProbeSpec(
    key="insider_sell_actual",
    seq=23,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-insider-sell-eod",
    context_group="cninfo_titles",
)


class InsiderSellActualProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_insider_sell_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if not payload:
            snap = await load_t1_snapshot(ctx.session, sym, "insider_sell_actual")
            if snap:
                return "insider_sell_actual", snap
            raw = ctx.raw_by_key.get("insider_sell_actual")
            raise ValueError(raw.get("blocker") if raw else "insider_sell_actual 未采集")

        metrics = compute_insider_sell_metrics(payload)
        node = build_insider_sell_actual_node(metrics, source=SOURCE_INSIDER)
        return "insider_sell_actual", node


PROBE = InsiderSellActualProbe()
