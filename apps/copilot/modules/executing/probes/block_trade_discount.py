"""#21 block_trade_discount · 探针模块。

[Ref: 28_ §3.2 #21]
"""
from __future__ import annotations

from apps.copilot.modules.executing.block_trade_discount import (
    SOURCE_BLOCK,
    compute_block_trade_discount_metrics,
    load_block_trade_payload,
)
from apps.copilot.modules.executing.indicator_nodes import build_block_trade_discount_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)

SPEC = ProbeSpec(
    key="block_trade_discount",
    seq=21,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-block-trade-eod",
    optional_silent=True,
)


class BlockTradeDiscountProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        payload = await load_block_trade_payload(
            ctx.session, sym, redis_client=ctx.redis_client
        )
        if not payload:
            raw = ctx.raw_by_key.get("block_trade_discount")
            if raw and raw.get("blocker"):
                raise ValueError(raw.get("blocker"))
            return None

        metrics = compute_block_trade_discount_metrics(payload)
        if metrics is None:
            return None
        node = build_block_trade_discount_node(metrics, source=SOURCE_BLOCK)
        return "block_trade_discount", node


PROBE = BlockTradeDiscountProbe()
