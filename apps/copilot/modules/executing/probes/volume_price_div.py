"""#16 volume_price_div · 探针模块。

[Ref: 28_ §3.2 #16]
"""
from __future__ import annotations

from apps.copilot.modules.executing.collectors.bars_15m import load_bars_15m_redis
from apps.copilot.modules.executing.indicator_nodes import build_volume_price_div_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_t1_snapshot
from apps.copilot.modules.executing.t1_operators.volume_price_div import (
    VolumePriceDivError,
    process_volume_price_div_from_redis,
)

SPEC = ProbeSpec(
    key="volume_price_div",
    seq=16,
    matrix="L4_Game",
    cadence="intraday_15m",
    job_id="l4-vol-div-15m",
    context_group="bars_15m",
)


class VolumePriceDivProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        cached = load_bars_15m_redis(ctx.redis_client, sym) if ctx.redis_client else None
        bars_payload: dict | None = cached
        if bars_payload is None:
            raw = ctx.raw_by_key.get("volume_price_div") or {}
            inner = raw.get("payload") or {}
            bars_payload = inner.get("bars_payload")

        if bars_payload:
            payload = process_volume_price_div_from_redis(bars_payload)
            node = build_volume_price_div_node(payload)
            return "volume_price_div", node

        snap = await load_t1_snapshot(ctx.session, sym, "volume_price_div")
        if snap:
            return "volume_price_div", snap

        raw = ctx.raw_by_key.get("volume_price_div") or {}
        preview = (raw.get("payload") or {}).get("t1_preview")
        if preview and preview.get("value") is not None:
            node = build_volume_price_div_node(
                {**preview, "source": raw.get("source") or preview.get("source") or ""}
            )
            return "volume_price_div", node

        raise VolumePriceDivError("Redis 15m 缓存缺失且 PG 无 bars_payload / T1 快照")


PROBE = VolumePriceDivProbe()
