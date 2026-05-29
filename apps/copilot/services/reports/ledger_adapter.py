"""SCS / EV 口径适配，供日报与周报聚合。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from apps.copilot.services.ledger.ev import EVCalculator
from apps.copilot.services.ledger.scs import SCSCalculator


class ReportLedgerAdapter:
    """对接 SCSCalculator / EVCalculator（按日快照与区间避险价值）。"""

    def __init__(self, session_factory) -> None:
        self._scs = SCSCalculator(session_factory)
        self._ev = EVCalculator(session_factory)

    async def snapshot_scs(self, user_id: str, day: date) -> float:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        r = await self._scs.calculate(user_id=user_id, start=start, end=end)
        return float(r.score)

    async def compute_avoided_loss(self, user_id: str, start: date, end: date) -> float:
        start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc) + timedelta(microseconds=1)
        r = await self._ev.calculate(user_id=user_id, start=start_dt, end=end_dt)
        return float(r.hedge_value)

    async def compute_earned(self, user_id: str, start: date, end: date) -> float:
        start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc) + timedelta(microseconds=1)
        r = await self._ev.calculate(user_id=user_id, start=start_dt, end=end_dt)
        return float(r.gain_value)
