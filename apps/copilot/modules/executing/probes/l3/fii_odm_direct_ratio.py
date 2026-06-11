"""#JL3 fii_odm_direct_ratio · ODM 直供占比。

[Ref: 28_ §2.2]
"""
from __future__ import annotations

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.indicator_node import (
    build_fii_odm_direct_ratio_node,
)
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t0_collect import (
    collect_fii_odm_direct_ratio_t0,
    parse_baseline_from_t1_json,
)
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.profile import load_profile, profile_l3_keys
from apps.copilot.modules.executing.storage import load_t0_raw_by_probe, load_t1_snapshot


SPEC = ProbeSpec(
    key="fii_odm_direct_ratio",
    seq=2,
    matrix="L3_Business",
    cadence="L3",
    job_id="l3-fii-odm-quarterly",
    t1_engine="python+deepseek",
    per_symbol=True,
)


class FiiOdmDirectRatioProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        raw = ctx.raw_by_key.get("fii_odm_direct_ratio")
        if not raw or not raw.get("ok"):
            raw = await load_t0_raw_by_probe(ctx.session, ctx.symbol, "fii_odm_direct_ratio")
        if not raw or not raw.get("ok"):
            prev = await load_t1_snapshot(ctx.session, ctx.symbol, "fii_odm_direct_ratio")
            baseline = parse_baseline_from_t1_json(prev.get("t1_json") if prev else None)
            t0_item = collect_fii_odm_direct_ratio_t0(
                ctx.symbol,
                historical_ratio_baseline_pct=baseline,
            )
            if not t0_item.get("ok"):
                raise ValueError((t0_item or {}).get("blocker") or "fii_odm_direct_ratio T0 未采集")
            payload = t0_item.get("payload") or {}
            source = t0_item.get("source") or "T0"
        else:
            payload = raw.get("payload") or {}
            source = raw.get("source") or "T0"
            prev = await load_t1_snapshot(ctx.session, ctx.symbol, "fii_odm_direct_ratio")
            bl = parse_baseline_from_t1_json(prev.get("t1_json") if prev else None)
            if bl is not None:
                payload = {**payload, "historical_ratio_baseline_pct": bl}

        prof = load_profile(ctx.symbol)
        if "fii_odm_direct_ratio" not in profile_l3_keys(prof):
            raise ValueError("profile 未启用 fii_odm_direct_ratio")

        node = build_fii_odm_direct_ratio_node(payload, source=source)
        return "fii_odm_direct_ratio", node


PROBE = FiiOdmDirectRatioProbe()
