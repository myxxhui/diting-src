"""#17 smart_money_flow · 探针模块。

[Ref: 28_ §3.2 #17]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_smart_money_flow_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.smart_money_flow import (
    SOURCE_TUSHARE,
    compute_smart_money_metrics,
    load_smart_money_payload,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot

SPEC = ProbeSpec(
    key="smart_money_flow",
    seq=17,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-smart-money-eod",
    context_group="moneyflow",
)


class SmartMoneyFlowProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_smart_money_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if payload is None:
            snap = await load_t1_snapshot(ctx.session, sym, "smart_money_flow")
            if snap:
                return "smart_money_flow", snap
            raw = ctx.raw_by_key.get("smart_money_flow")
            raise ValueError(raw.get("blocker") if raw else "smart_money_flow 未采集")

        metrics = compute_smart_money_metrics(payload)
        node = build_smart_money_flow_node(metrics, source=SOURCE_TUSHARE)
        return "smart_money_flow", node


PROBE = SmartMoneyFlowProbe()
