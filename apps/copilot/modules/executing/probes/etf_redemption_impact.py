"""#24 etf_redemption_impact · 探针模块。

[Ref: 28_ §3.2 #24]
"""
from __future__ import annotations

from apps.copilot.modules.executing.etf_redemption_impact import (
    SOURCE_ETF,
    compute_etf_redemption_metrics,
    load_etf_redemption_payload,
)
from apps.copilot.modules.executing.indicator_nodes import build_etf_redemption_impact_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)

SPEC = ProbeSpec(
    key="etf_redemption_impact",
    seq=24,
    matrix="L4_Game",
    cadence="L2",
    job_id="l4-etf-redemption-morning",
    optional_silent=True,
    context_group="_global",
)


class EtfRedemptionImpactProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_etf_redemption_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if not payload:
            raw = ctx.raw_by_key.get("etf_redemption_impact")
            if raw and raw.get("blocker"):
                raise ValueError(raw.get("blocker"))
            return None

        metrics = compute_etf_redemption_metrics(payload)
        if metrics is None:
            return None
        node = build_etf_redemption_impact_node(metrics, source=SOURCE_ETF)
        return "etf_redemption_impact", node


PROBE = EtfRedemptionImpactProbe()
