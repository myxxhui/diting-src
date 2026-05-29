"""自我熔断 3 触发条件 + 重置流程测试。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from apps.copilot.db.models import User, UserDecision
from apps.copilot.services.alerts.models import AlertLog
from apps.copilot.services.circuit_breaker import (
    PAUSE_KEY,
    BreakerReason,
    SelfCircuitBreaker,
)
from apps.copilot.services.ledger.models import MonthlyReport


@pytest.mark.asyncio
async def test_not_interested_streak_triggers(db_session, fake_redis):
    u = User(user_id="u1", name="u1")
    db_session.add(u)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    for i in range(3):
        db_session.add(
            UserDecision(
                user_pk=u.id,
                thesis_id=f"t{i}",
                action="not_interested",
                decided_at=now - timedelta(minutes=i),
            )
        )
    await db_session.commit()

    cb = SelfCircuitBreaker(db_session, fake_redis)
    result = await cb.check_all("u1")
    assert result.triggered is True
    assert result.reason == BreakerReason.NOT_INTERESTED_STREAK

    await cb.trigger("u1", result)
    assert await cb.is_paused() is True


@pytest.mark.asyncio
async def test_not_interested_broken_by_join(db_session, fake_redis):
    u = User(user_id="u1", name="u1")
    db_session.add(u)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(
        UserDecision(
            user_pk=u.id,
            thesis_id="j",
            action="join",
            decided_at=now - timedelta(days=10),
        )
    )
    for i in range(3):
        db_session.add(
            UserDecision(
                user_pk=u.id,
                thesis_id=f"t{i}",
                action="not_interested",
                decided_at=now - timedelta(minutes=i),
            )
        )
    await db_session.commit()

    cb = SelfCircuitBreaker(db_session, fake_redis)
    result = await cb.check_all("u1")
    assert result.triggered is False


@pytest.mark.asyncio
async def test_scs_low_triggers(db_session, fake_redis):
    today = date.today()
    db_session.add(
        MonthlyReport(
            user_id="u1",
            year=today.year,
            month=today.month,
            scs=25.0,
            ev=0.0,
            octant_distribution={},
            summary={},
        )
    )
    await db_session.commit()

    cb = SelfCircuitBreaker(db_session, fake_redis)
    result = await cb.check_all("u1")
    assert result.triggered is True
    assert result.reason == BreakerReason.SCS_TOO_LOW


@pytest.mark.asyncio
async def test_delivery_fail_streak_triggers(db_session, fake_redis):
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(
            AlertLog(
                alert_id=f"a{i}",
                user_id="u1",
                level="red",
                alert_type="stop_loss",
                symbol="600519",
                name="n",
                message="x",
                payload={},
                dedup_key=f"dk{i}",
                channels_sent={"wechat": False, "telegram": False, "email": False},
                sla_met=False,
                created_at=now - timedelta(minutes=i),
            )
        )
    await db_session.commit()

    cb = SelfCircuitBreaker(db_session, fake_redis)
    result = await cb.check_all("u1")
    assert result.triggered is True
    assert result.reason == BreakerReason.DELIVERY_FAIL_STREAK


@pytest.mark.asyncio
async def test_delivery_recovery_breaks_streak(db_session, fake_redis):
    now = datetime.now(timezone.utc)
    for i in range(4):
        db_session.add(
            AlertLog(
                alert_id=f"a{i}",
                user_id="u1",
                level="red",
                alert_type="x",
                symbol="x",
                name="n",
                message="x",
                payload={},
                dedup_key=f"d{i}",
                channels_sent={"wechat": False, "telegram": False, "email": False},
                sla_met=False,
                created_at=now - timedelta(minutes=i + 1),
            )
        )
    db_session.add(
        AlertLog(
            alert_id="recover",
            user_id="u1",
            level="red",
            alert_type="x",
            symbol="x",
            name="n",
            message="x",
            payload={},
            dedup_key="dr",
            channels_sent={"wechat": True, "telegram": False, "email": False},
            sla_met=True,
            created_at=now,
        )
    )
    await db_session.commit()

    cb = SelfCircuitBreaker(db_session, fake_redis)
    result = await cb.check_all("u1")
    assert result.triggered is False


@pytest.mark.asyncio
async def test_reset_clears_pause(db_session, fake_redis):
    await fake_redis.set(PAUSE_KEY, "manual_test", ex=600)
    cb = SelfCircuitBreaker(db_session, fake_redis)
    assert await cb.is_paused() is True
    res = await cb.reset(operator="architect", note="人工恢复")
    assert res["ok"] is True
    assert await cb.is_paused() is False


@pytest.mark.asyncio
async def test_status_returns_ttl(db_session, fake_redis):
    await fake_redis.set(PAUSE_KEY, "scs_too_low", ex=600)
    cb = SelfCircuitBreaker(db_session, fake_redis)
    status = await cb.status()
    assert status["paused"] is True
    assert status["ttl_seconds"] > 0
    assert status["reason"] == "scs_too_low"
