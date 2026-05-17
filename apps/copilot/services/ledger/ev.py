"""EV（Economic Value）= 避险价值 + 增益价值 - 卖飞成本。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select

from apps.copilot.services.ledger.models import AttributionRecord


@dataclass
class EVResult:
    total: float
    hedge_value: float
    gain_value: float
    cost_value: float
    sample_count: int


class EVCalculator:
    HEDGE_OCTANTS = ("C", "F")
    GAIN_OCTANTS = ("A",)
    COST_OCTANTS = ("H",)

    def __init__(self, session_factory):
        self._sf = session_factory

    async def calculate(self, *, user_id: str, start: datetime, end: datetime) -> EVResult:
        async with self._sf() as session:
            rows = (
                await session.execute(
                    select(AttributionRecord.octant, AttributionRecord.ev_delta).where(
                        and_(
                            AttributionRecord.user_id == user_id,
                            AttributionRecord.created_at >= start,
                            AttributionRecord.created_at < end,
                        )
                    )
                )
            ).all()

        hedge = sum(d for o, d in rows if o in self.HEDGE_OCTANTS)
        gain = sum(d for o, d in rows if o in self.GAIN_OCTANTS)
        cost = sum(abs(d) for o, d in rows if o in self.COST_OCTANTS)
        total = float(hedge + gain - cost)

        return EVResult(
            total=round(total, 2),
            hedge_value=round(float(hedge), 2),
            gain_value=round(float(gain), 2),
            cost_value=round(float(cost), 2),
            sample_count=len(rows),
        )
