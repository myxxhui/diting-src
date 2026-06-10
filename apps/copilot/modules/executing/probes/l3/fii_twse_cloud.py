"""#JL3 fii_twse_cloud · 母公司云端营收。

[Ref: 28_ §2.2 fii_twse_cloud]
"""
from __future__ import annotations

from apps.copilot.modules.executing.l3.fii_twse_cloud.indicator_node import build_fii_twse_cloud_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot
from apps.copilot.modules.executing.profile import load_profile

SPEC = ProbeSpec(
    key="fii_twse_cloud",
    seq=1,
    matrix="L3_Business",
    cadence="L3",
    job_id="l3-fii-twse-monthly",
    t1_engine="python",
    per_symbol=True,
)


class FiiTwseCloudProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        raw = ctx.raw_by_key.get("fii_twse_cloud")
        if not raw or not raw.get("ok"):
            snap = await load_t1_snapshot(ctx.session, ctx.symbol, "fii_twse_cloud")
            if snap:
                return "fii_twse_cloud", snap
            raise ValueError((raw or {}).get("blocker") or "fii_twse_cloud T0 未采集")

        payload = raw.get("payload") or {}
        prof = load_profile(ctx.symbol)
        twse = str(prof.get("honhai_twse_code") or "2317.TW")
        source = f"{raw.get('source') or 'T0'} · parent {twse}"
        node = build_fii_twse_cloud_node(payload, source=source)
        return "fii_twse_cloud", node


PROBE = FiiTwseCloudProbe()
