"""#25 tech_beta_correlation · 探针模块。

[Ref: 28_ §2.2.8]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import build_tech_beta_correlation_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot
from apps.copilot.modules.executing.tech_beta_correlation import (
    SOURCE_BETA,
    compute_tech_beta_correlation_metrics,
    load_tech_beta_correlation_payload,
    resolve_sector_index,
)

SPEC = ProbeSpec(
    key="tech_beta_correlation",
    seq=25,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-beta-correlation-eod",
    context_group="index_daily",
)


class TechBetaCorrelationProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        from apps.copilot.modules.executing.profile import load_profile

        try:
            resolve_sector_index(load_profile(sym))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        payload = await load_tech_beta_correlation_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if payload is None:
            snap = await load_t1_snapshot(ctx.session, sym, "tech_beta_correlation")
            if snap:
                return "tech_beta_correlation", snap
            raw = ctx.raw_by_key.get("tech_beta_correlation")
            raise ValueError(raw.get("blocker") if raw else "tech_beta_correlation 未采集")

        metrics = compute_tech_beta_correlation_metrics(payload)
        node = build_tech_beta_correlation_node(metrics, source=SOURCE_BETA)
        return "tech_beta_correlation", node


PROBE = TechBetaCorrelationProbe()
