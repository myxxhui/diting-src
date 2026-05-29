"""P4·事件探针(6h 调度).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any

from apps.state_watch.probes.base_probe import BaseProbe, ProbeResult
from apps.state_watch.probes.datasource.announcement_adapter import CorporateEvent, fetch_events

_SEVERITY_WEIGHT = {"low": 0.3, "medium": 0.6, "high": 1.0}


def aggregate_events(events: list[CorporateEvent]) -> dict[str, Any]:
    now = datetime.utcnow()

    def _within(ev: CorporateEvent, days: int, etype: str) -> bool:
        return ev.event_type == etype and (now - ev.event_date).days <= days

    major_reduce = sum(ev.amount for ev in events if _within(ev, 30, "reduce"))
    pledge_ratio = max((ev.amount for ev in events if _within(ev, 365, "pledge")), default=0.0)
    exec_change = sum(1 for ev in events if _within(ev, 90, "exec_change"))
    litigation = sum(1 for ev in events if _within(ev, 180, "litigation"))
    penalty = sum(1 for ev in events if _within(ev, 180, "penalty"))

    severity_score = 0.0
    for ev in events:
        if (now - ev.event_date).days <= 90:
            severity_score = max(severity_score, _SEVERITY_WEIGHT.get(ev.severity, 0.3))

    return {
        "major_reduce_30d": round(major_reduce, 6),
        "pledge_ratio": round(pledge_ratio, 6),
        "exec_change_count_90d": exec_change,
        "litigation_count_180d": litigation,
        "penalty_count_180d": penalty,
        "max_severity_90d": round(severity_score, 4),
        "events_recent": [
            {
                "event_type": ev.event_type,
                "event_date": ev.event_date.isoformat(),
                "description": ev.description,
                "severity": ev.severity,
                "amount": ev.amount,
            }
            for ev in events[:10]
        ],
    }


class EventProbe(BaseProbe):
    probe_type = "event"
    timeout_seconds = 15.0
    interval_hours = 6

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        evs = await asyncio.to_thread(fetch_events, symbol, 180)
        return aggregate_events(evs)


async def _cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    probe = EventProbe()
    result: ProbeResult = await probe.fetch(args.symbol)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_cli())
