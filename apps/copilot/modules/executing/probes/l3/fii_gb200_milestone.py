"""#JL3 fii_gb200_milestone · GB200 量产节点。

[Ref: 28_ §2.2 fii_gb200_milestone]
"""
from __future__ import annotations

from apps.copilot.modules.executing.l3.fii_gb200_milestone.indicator_node import (
    build_fii_gb200_milestone_blocker_node,
    build_fii_gb200_milestone_node,
)
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.prior_snapshot import (
    prior_lifecycle_stage_from_t1,
    prior_signal_snapshot_from_t1,
)
from apps.copilot.modules.executing.storage import load_t0_raw_by_probe, load_t1_snapshot


SPEC = ProbeSpec(
    key="fii_gb200_milestone",
    seq=3,
    matrix="L3_Business",
    cadence="L3",
    job_id="l3-fii-gb200-milestone",
    t1_engine="python",
    per_symbol=True,
)


class FiiGb200MilestoneProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        raw = ctx.raw_by_key.get("fii_gb200_milestone")
        if not raw or not raw.get("ok"):
            raw = await load_t0_raw_by_probe(ctx.session, ctx.symbol, "fii_gb200_milestone")
        if not raw or not raw.get("ok"):
            prev = await load_t1_snapshot(ctx.session, ctx.symbol, "fii_gb200_milestone")
            prior_snap = prior_signal_snapshot_from_t1(prev)
            prior_stage = prior_lifecycle_stage_from_t1(prev)
            from apps.copilot.modules.executing.l3.fii_gb200_milestone.t0_collect import (
                collect_fii_gb200_milestone_t0,
            )

            t0_item = collect_fii_gb200_milestone_t0(
                ctx.symbol,
                prior_lifecycle_stage=prior_stage,
                prior_signal_snapshot=prior_snap,
            )
            if not t0_item.get("ok"):
                blocker = str(t0_item.get("blocker") or "fii_gb200_milestone T0 未采集")
                node = build_fii_gb200_milestone_blocker_node(
                    blocker,
                    source=t0_item.get("source") or "T0",
                )
                return "fii_gb200_milestone", node
            raw = t0_item

        payload = dict(raw.get("payload") or {})
        if not payload.get("prior_signal_snapshot"):
            prev = await load_t1_snapshot(ctx.session, ctx.symbol, "fii_gb200_milestone")
            snap = prior_signal_snapshot_from_t1(prev)
            if snap:
                payload["prior_signal_snapshot"] = snap
                if not payload.get("prior_lifecycle_stage"):
                    payload["prior_lifecycle_stage"] = snap.get("signal_status")
        node = build_fii_gb200_milestone_node(
            payload,
            source=raw.get("source") or "T0",
        )
        return "fii_gb200_milestone", node


PROBE = FiiGb200MilestoneProbe()
