"""sync-status API 数据。

[Ref: 28_ §4.6]
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import utc_naive_to_shanghai_display
from apps.copilot.db.models import ExecutingT0ProbeState, ExecutingT0SyncWatermark
from apps.copilot.modules.executing.profile import load_profile, profile_enabled_probe_keys
from apps.copilot.modules.executing.universe import load_executing_collect_symbols


def _expected_keys_by_symbol(symbols: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for sym in symbols:
        prof = load_profile(sym)
        out[sym] = set(profile_enabled_probe_keys(prof))
    return out


async def build_sync_status(session: AsyncSession) -> dict[str, Any]:
    symbols = await load_executing_collect_symbols(session)
    expected = _expected_keys_by_symbol(symbols)
    wm = list((await session.scalars(select(ExecutingT0SyncWatermark))).all())
    probes = list(
        (
            await session.scalars(
                select(ExecutingT0ProbeState).where(
                    ExecutingT0ProbeState.symbol.in_(symbols) if symbols else True
                )
            )
        ).all()
    )
    now = datetime.utcnow()
    stale_probes = []
    for p in probes:
        if p.probe_key not in expected.get(p.symbol, set()):
            continue
        if p.status != "ok":
            stale_probes.append({"symbol": p.symbol, "key": p.probe_key, "status": p.status, "blocker": p.blocker})
        elif p.stale_after and p.stale_after < now:
            stale_probes.append({"symbol": p.symbol, "key": p.probe_key, "status": "stale"})

    missing_total = []
    for sym in symbols:
        have = {
            p.probe_key
            for p in probes
            if p.symbol == sym and p.status == "ok" and p.probe_key in expected.get(sym, set())
        }
        for k in sorted(expected.get(sym, set())):
            if k not in have:
                missing_total.append({"symbol": sym, "key": k})

    return {
        "collect_symbols": symbols,
        "watermarks": [
            {
                "job_id": w.job_id,
                "symbol": w.symbol,
                "last_success_at": w.last_success_at.isoformat() if w.last_success_at else None,
                "last_success_at_cst": utc_naive_to_shanghai_display(w.last_success_at),
                "last_error": w.last_error,
            }
            for w in wm
        ],
        "stale_count": len(stale_probes),
        "stale_probes": stale_probes[:50],
        "missing_count": len(missing_total),
    }
