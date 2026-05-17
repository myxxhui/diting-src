"""SCS（System Contribution Score）计算引擎。

口径（启动期版）：
    基础分 = 50
    SCS = clip(基础分 + Σ(scs_delta_i) - 决策迟滞罚分, 0, 100)
    决策迟滞罚分：响应时长 > lag_threshold_seconds 时 lag_penalty_per/条

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import and_, select

from apps.copilot.services.ledger.models import AttributionRecord, UserResponse

BASE_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0


@dataclass
class SCSResult:
    score: float
    base: float
    contribution_sum: float
    lag_penalty: float
    sample_count: int


def _clip(v: float, lo: float = MIN_SCORE, hi: float = MAX_SCORE) -> float:
    return max(lo, min(hi, v))


class SCSCalculator:
    def __init__(
        self,
        session_factory,
        *,
        lag_threshold_seconds: int = 600,
        lag_penalty_per: float = 0.5,
    ):
        self._sf = session_factory
        self._lag_threshold = lag_threshold_seconds
        self._lag_penalty = lag_penalty_per

    async def calculate(
        self,
        *,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> SCSResult:
        async with self._sf() as session:
            rows = (
                await session.execute(
                    select(AttributionRecord.scs_delta).where(
                        and_(
                            AttributionRecord.user_id == user_id,
                            AttributionRecord.created_at >= start,
                            AttributionRecord.created_at < end,
                        )
                    )
                )
            ).scalars().all()
            contribution_sum = float(sum(rows))
            sample = len(rows)

            resp_rows = (
                await session.execute(
                    select(UserResponse.advice_ts, UserResponse.response_ts).where(
                        and_(
                            UserResponse.user_id == user_id,
                            UserResponse.response_ts >= start,
                            UserResponse.response_ts < end,
                        )
                    )
                )
            ).all()

        lag_count = 0
        for advice_ts, response_ts in resp_rows:
            if not advice_ts or not response_ts:
                continue
            delta = (response_ts - advice_ts).total_seconds()
            if delta > self._lag_threshold:
                lag_count += 1
        lag_penalty = lag_count * self._lag_penalty

        score = _clip(BASE_SCORE + contribution_sum - lag_penalty)
        return SCSResult(
            score=round(score, 2),
            base=BASE_SCORE,
            contribution_sum=round(contribution_sum, 2),
            lag_penalty=round(lag_penalty, 2),
            sample_count=sample,
        )

    @staticmethod
    def aggregate(deltas: Iterable[float]) -> float:
        return _clip(BASE_SCORE + float(sum(deltas)))
