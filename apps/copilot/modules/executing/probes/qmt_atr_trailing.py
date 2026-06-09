"""#15 qmt_atr_trailing · 探针模块。

[Ref: 28_ §3.2 #15]
"""
from __future__ import annotations

from apps.copilot.modules.executing.collectors.daily_bars import LOOKBACK_TRADING_DAYS
from apps.copilot.modules.executing.collectors.intraday_draft import (
    load_draft_bar,
    load_draft_bar_dict,
    merge_pg_rows_with_draft,
)
from apps.copilot.modules.executing.indicator_nodes import build_qmt_atr_trailing_node
from apps.copilot.modules.executing.probes._base import (
    ExecutingProbe,
    OperatorResult,
    ProbeSpec,
    T1LiveContext,
)
from apps.copilot.modules.executing.storage import load_daily_bars, load_t1_snapshot
from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
    AtrTrailingError,
    SOURCE_PG,
    process_qmt_atr_trailing_from_rows,
)

SPEC = ProbeSpec(
    key="qmt_atr_trailing",
    seq=15,
    matrix="L4_Game",
    cadence="daily",
    job_id="l4-atr-bars-sync",
    context_group="daily_bars",
)


class QmtAtrTrailingProbe(ExecutingProbe):
    spec = SPEC

    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        sym = ctx.symbol.zfill(6)[-6:]
        pg_rows = await load_daily_bars(ctx.session, sym, limit=LOOKBACK_TRADING_DAYS)
        draft = load_draft_bar(ctx.redis_client, sym) if ctx.redis_client else None
        if draft is not None:
            merged = merge_pg_rows_with_draft(pg_rows, draft)
            payload = process_qmt_atr_trailing_from_rows(
                merged,
                ctx.entry_date,
                source=SOURCE_PG,
            )
            payload["intraday"] = True
            draft_meta = load_draft_bar_dict(ctx.redis_client, sym) if ctx.redis_client else None
            if draft_meta and draft_meta.get("collected_at"):
                payload["last_tick_time"] = draft_meta["collected_at"]
        elif pg_rows:
            payload = process_qmt_atr_trailing_from_rows(
                pg_rows,
                ctx.entry_date,
                source=SOURCE_PG,
            )
        else:
            snap = await load_t1_snapshot(ctx.session, sym, "qmt_atr_trailing")
            if snap:
                return "qmt_atr_trailing", snap
            raise AtrTrailingError(f"无 PG 底库且无 Redis 草稿 symbol={sym}")

        node = build_qmt_atr_trailing_node(payload)
        return "qmt_atr_trailing", node


PROBE = QmtAtrTrailingProbe()
