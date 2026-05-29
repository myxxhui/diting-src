"""自我熔断器（Redis 暂停 + audit_log + 架构师通知）。

3 触发条件：
1. 连续 3 次推荐被用户标记 not_interested 且后续 30 天未触发 join
2. 当月月报 SCS < 30（取当月最新 MonthlyReport）
3. 连续 5 次告警推送通道全部失败

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any

import redis.asyncio as redis
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.config import settings
from apps.copilot.db.models import AuditLog, User, UserDecision
from apps.copilot.services.alerts.models import AlertLog
from apps.copilot.services.ledger.models import MonthlyReport

log = logging.getLogger(__name__)

PAUSE_KEY = "copilot:circuit_breaker:pause"
PAUSE_TTL_SECONDS = 86_400


class BreakerReason(str, Enum):
    NOT_INTERESTED_STREAK = "not_interested_streak"
    SCS_TOO_LOW = "scs_too_low"
    DELIVERY_FAIL_STREAK = "delivery_fail_streak"


@dataclass
class BreakerCheckResult:
    triggered: bool
    reason: BreakerReason | None
    detail: dict[str, Any]


class SelfCircuitBreaker:
    def __init__(self, session: AsyncSession, redis_client: redis.Redis) -> None:
        self.session = session
        self.redis = redis_client

    async def is_paused(self) -> bool:
        return bool(await self.redis.exists(PAUSE_KEY))

    async def check_all(self, user_id: str) -> BreakerCheckResult:
        for checker in (self._check_not_interested, self._check_scs, self._check_delivery_failures):
            result = await checker(user_id)
            if result.triggered:
                return result
        return BreakerCheckResult(triggered=False, reason=None, detail={})

    async def trigger(self, user_id: str, result: BreakerCheckResult) -> None:
        if not result.triggered or result.reason is None:
            return
        await self.redis.set(PAUSE_KEY, result.reason.value, ex=PAUSE_TTL_SECONDS)
        await self._notify_architect(result)
        until = datetime.now(timezone.utc) + timedelta(seconds=PAUSE_TTL_SECONDS)
        self.session.add(
            AuditLog(
                kind="circuit_break",
                payload={
                    "user_id": user_id,
                    "reason": result.reason.value,
                    "detail": result.detail,
                    "paused_until": until.isoformat(),
                },
            )
        )
        await self.session.commit()
        log.warning("[circuit_breaker] TRIGGERED reason=%s detail=%s", result.reason, result.detail)

    async def reset(self, operator: str, note: str = "") -> dict[str, Any]:
        await self.redis.delete(PAUSE_KEY)
        self.session.add(
            AuditLog(
                kind="circuit_break_reset",
                payload={"operator": operator, "note": note},
            )
        )
        await self.session.commit()
        return {"ok": True, "operator": operator}

    async def status(self) -> dict[str, Any]:
        paused = await self.is_paused()
        if not paused:
            return {"paused": False, "ttl_seconds": 0, "reason": None}
        ttl = await self.redis.ttl(PAUSE_KEY)
        raw = await self.redis.get(PAUSE_KEY)
        if isinstance(raw, bytes):
            reason = raw.decode()
        else:
            reason = raw
        return {
            "paused": True,
            "ttl_seconds": max(int(ttl), 0),
            "reason": reason,
        }

    async def _check_not_interested(self, user_id: str) -> BreakerCheckResult:
        stmt = (
            select(UserDecision)
            .join(User, User.id == UserDecision.user_pk)
            .where(User.user_id == user_id)
            .order_by(desc(UserDecision.decided_at))
            .limit(3)
        )
        latest3 = (await self.session.execute(stmt)).scalars().all()
        if len(latest3) < 3 or any(d.action != "not_interested" for d in latest3):
            return BreakerCheckResult(False, None, {})

        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        join_q = (
            select(func.count())
            .select_from(UserDecision)
            .join(User, User.id == UserDecision.user_pk)
            .where(
                User.user_id == user_id,
                UserDecision.action == "join",
                UserDecision.decided_at >= thirty_days_ago,
            )
        )
        join_count = (await self.session.execute(join_q)).scalar_one()
        if int(join_count) == 0:
            return BreakerCheckResult(
                True,
                BreakerReason.NOT_INTERESTED_STREAK,
                {
                    "streak": 3,
                    "join_count_30d": 0,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return BreakerCheckResult(False, None, {})

    async def _check_scs(self, user_id: str) -> BreakerCheckResult:
        today = date.today()
        stmt = (
            select(MonthlyReport)
            .where(
                MonthlyReport.user_id == user_id,
                MonthlyReport.year == today.year,
                MonthlyReport.month == today.month,
            )
            .order_by(desc(MonthlyReport.generated_at))
            .limit(1)
        )
        latest = (await self.session.execute(stmt)).scalar_one_or_none()
        if latest and latest.scs < 30:
            return BreakerCheckResult(
                True,
                BreakerReason.SCS_TOO_LOW,
                {"month": f"{latest.year}-{latest.month:02d}", "scs": float(latest.scs)},
            )
        return BreakerCheckResult(False, None, {})

    async def _check_delivery_failures(self, user_id: str) -> BreakerCheckResult:
        stmt = (
            select(AlertLog)
            .where(AlertLog.user_id == user_id)
            .order_by(desc(AlertLog.created_at))
            .limit(5)
        )
        latest5 = (await self.session.execute(stmt)).scalars().all()
        if len(latest5) < 5:
            return BreakerCheckResult(False, None, {})

        def any_ok(channels_sent: Any) -> bool:
            if not channels_sent:
                return False
            if isinstance(channels_sent, dict):
                return any(bool(v) for v in channels_sent.values())
            if isinstance(channels_sent, list):
                return any(
                    bool(item.get("success") if isinstance(item, dict) else item) for item in channels_sent
                )
            return False

        if all(not any_ok(a.channels_sent) for a in latest5):
            return BreakerCheckResult(
                True,
                BreakerReason.DELIVERY_FAIL_STREAK,
                {"streak": 5, "first_alert_id": latest5[0].alert_id},
            )
        return BreakerCheckResult(False, None, {})

    async def _notify_architect(self, result: BreakerCheckResult) -> None:
        if not settings.architect_wechat_webhook:
            log.warning("architect_wechat_webhook 未配置，跳过通知")
            return
        import httpx

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": (
                    f"# ⚠️ 副驾驶熔断\n"
                    f"**原因**：{result.reason.value if result.reason else 'unknown'}\n\n"
                    f"**详情**：```{result.detail}```\n\n"
                    f"**自动暂停推送**：{PAUSE_TTL_SECONDS // 3600}h"
                )
            },
        }
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(settings.architect_wechat_webhook, json=payload)
