"""用户响应记录器：推荐 join/consider/not_interested；告警 sold/not_sold。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from apps.copilot.services.ledger.models import ResponseKind, UserResponse


class UserResponseRecorder:
    def __init__(self, session_factory):
        self._sf = session_factory

    async def record_recommendation(
        self,
        *,
        user_id: str,
        thesis_id: str,
        symbol: str,
        system_advice: str,
        user_action: str,
        advice_ts: datetime,
    ) -> int:
        return await self._upsert(
            user_id=user_id,
            kind=ResponseKind.RECOMMENDATION.value,
            ref_id=thesis_id,
            symbol=symbol,
            system_advice=system_advice,
            user_action=user_action,
            advice_ts=advice_ts,
        )

    async def record_alert(
        self,
        *,
        user_id: str,
        alert_id: str,
        symbol: str,
        system_advice: str,
        user_action: str,
        advice_ts: datetime,
    ) -> int:
        return await self._upsert(
            user_id=user_id,
            kind=ResponseKind.ALERT.value,
            ref_id=alert_id,
            symbol=symbol,
            system_advice=system_advice,
            user_action=user_action,
            advice_ts=advice_ts,
        )

    async def _upsert(self, **kw) -> int:
        kw.setdefault("response_ts", datetime.now(timezone.utc))
        async with self._sf() as session:
            stmt = sqlite_insert(UserResponse).values(**kw)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "ref_id", "kind"],
                set_={
                    "user_action": kw["user_action"],
                    "response_ts": kw["response_ts"],
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (
                await session.execute(
                    select(UserResponse.id)
                    .where(UserResponse.user_id == kw["user_id"])
                    .where(UserResponse.ref_id == kw["ref_id"])
                    .where(UserResponse.kind == kw["kind"])
                )
            ).scalar_one()
            return int(row)
