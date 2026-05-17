"""自我熔断：滑动窗口内 B+H 占比 ≥ 阈值 → 暂停推送 + 通知架构师。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import desc, select, update

from apps.copilot.services.ledger.models import AttributionRecord, CircuitBreakerState

logger = logging.getLogger(__name__)

Notifier = Callable[[str, str], Awaitable[None]]


class CircuitBreaker:
    def __init__(
        self,
        session_factory,
        *,
        window_size: int = 20,
        bh_threshold: float = 0.35,
        notifier: Optional[Notifier] = None,
    ):
        self._sf = session_factory
        self._window = window_size
        self._threshold = bh_threshold
        self._notifier = notifier

    async def evaluate(self, user_id: str) -> CircuitBreakerState:
        should_pause = False
        state: Optional[CircuitBreakerState] = None
        window_size = 0
        bh_count = 0
        ratio = 0.0

        async with self._sf() as session:
            rows = (
                await session.execute(
                    select(AttributionRecord.octant)
                    .where(AttributionRecord.user_id == user_id)
                    .order_by(desc(AttributionRecord.created_at))
                    .limit(self._window)
                )
            ).scalars().all()

            window_size = len(rows)
            bh_count = sum(1 for o in rows if o in ("B", "H"))
            ratio = (bh_count / window_size) if window_size else 0.0
            should_pause = window_size >= self._window and ratio >= self._threshold

            state = (await session.execute(select(CircuitBreakerState).limit(1))).scalar_one_or_none()
            now = datetime.now(timezone.utc)

            if state is None:
                state = CircuitBreakerState(
                    paused=should_pause,
                    reason=(
                        f"启动期初始化；window={window_size}; bh_ratio={ratio:.2f}"
                        f"; threshold={self._threshold:.2f}"
                    ),
                    last_window_size=window_size,
                    last_bh_ratio=ratio,
                    updated_at=now,
                )
                session.add(state)
            else:
                previously_paused = bool(state.paused)
                state.paused = should_pause
                state.last_window_size = window_size
                state.last_bh_ratio = ratio
                state.updated_at = now
                if should_pause and not previously_paused:
                    state.reason = (
                        f"自动熔断：最近 {window_size} 条决策中 B+H 占比 {ratio:.2%}"
                        f" ≥ 阈值 {self._threshold:.2%}"
                    )
                elif (not should_pause) and previously_paused:
                    state.reason = "自动恢复：B+H 占比已回落至阈值以下"

            await session.commit()
            await session.refresh(state)

        if should_pause and self._notifier is not None:
            await self._notifier(
                "🚨 价值账本自我熔断已触发",
                state.reason,
            )

        logger.info(
            "circuit eval user=%s window=%d bh=%d ratio=%.3f paused=%s",
            user_id,
            window_size,
            bh_count,
            ratio,
            should_pause,
        )
        return state

    async def is_paused(self) -> bool:
        async with self._sf() as session:
            state = (await session.execute(select(CircuitBreakerState).limit(1))).scalar_one_or_none()
            return bool(state.paused) if state else False

    async def force_resume(self, reason: str = "manual_resume") -> None:
        now = datetime.now(timezone.utc)
        async with self._sf() as session:
            await session.execute(
                update(CircuitBreakerState).values(
                    paused=False,
                    reason=reason,
                    updated_at=now,
                )
            )
            await session.commit()
