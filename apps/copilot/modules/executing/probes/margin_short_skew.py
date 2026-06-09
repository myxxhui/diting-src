"""#19 margin_short_skew · 探针模块。

[Ref: 28_ §3.2 #19]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_margin_short_skew_node
from apps.copilot.modules.executing.margin_short_skew import (
    SOURCE_MARGIN,
    compute_margin_short_skew_metrics,
    load_margin_skew_payload,
)
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot

SPEC = ProbeSpec(
    key="margin_short_skew",
    seq=19,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-margin-skew-morning",
    context_group="margin_detail",
)


class MarginShortSkewProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_margin_skew_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if payload is None:
            snap = await load_t1_snapshot(ctx.session, sym, "margin_short_skew")
            if snap:
                return "margin_short_skew", snap
            raw = ctx.raw_by_key.get("margin_short_skew")
            raise ValueError(raw.get("blocker") if raw else "margin_short_skew 未采集")

        metrics = compute_margin_short_skew_metrics(payload)
        node = build_margin_short_skew_node(metrics, source=SOURCE_MARGIN)
        return "margin_short_skew", node


PROBE = MarginShortSkewProbe()
