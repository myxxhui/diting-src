"""M3 告警系统测试。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.copilot.db.database import Base
from apps.copilot.services.alerts.channels.base import ChannelResult
from apps.copilot.services.alerts.channels.email import EmailChannel
from apps.copilot.services.alerts.channels.telegram import TelegramChannel
from apps.copilot.services.alerts.channels.wechat import WechatChannel
from apps.copilot.services.alerts.dedup import AlertDeduper
from apps.copilot.services.alerts.dispatcher import AlertDispatcher, map_event_to_alert
from apps.copilot.services.alerts.models import ALERT_LEVEL_MAP, Alert, AlertLevel, AlertType
from apps.copilot.services.alerts.sla_monitor import SLAMonitor


@pytest_asyncio.fixture
async def session_factory():
    from apps.copilot.db import models as db_models  # noqa: F401
    from apps.copilot.services.alerts.models import AlertLog  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_level_map_red_count():
    reds = [t for t, lv in ALERT_LEVEL_MAP.items() if lv == AlertLevel.RED]
    oranges = [t for t, lv in ALERT_LEVEL_MAP.items() if lv == AlertLevel.ORANGE]
    assert len(reds) == 4 and len(oranges) == 2


def test_map_event_reject():
    event = {
        "symbol": "002450",
        "name": "康得新",
        "aggregation_reason": "存贷双高 + 现金流背离",
    }
    alert = map_event_to_alert("u1", "events:cryo_guard:reject", event)
    assert alert is not None
    assert alert.alert_type == AlertType.REJECT
    assert alert.level == AlertLevel.RED
    assert "存贷双高" in alert.message


def test_map_event_health_drop_below_threshold_returns_none():
    event = {"symbol": "000001", "name": "平安银行", "health_delta": -5.0, "node_state": {}}
    assert map_event_to_alert("u1", "events:monitor:health_change", event) is None


def test_map_event_health_drop_triggers_red():
    event = {
        "symbol": "000001",
        "name": "平安银行",
        "health_delta": -23.0,
        "change_reason": "Q2 不及预期",
        "node_state": {},
    }
    alert = map_event_to_alert("u1", "events:monitor:health_change", event)
    assert alert.alert_type == AlertType.HEALTH_DROP
    assert alert.level == AlertLevel.RED


def test_map_event_thesis_invalid_orange():
    event = {
        "symbol": "000001",
        "name": "平安银行",
        "health_delta": -3.0,
        "node_state": {"thesis_status": "invalid"},
        "change_reason": "叙事破坏",
    }
    alert = map_event_to_alert("u1", "events:monitor:health_change", event)
    assert alert.alert_type == AlertType.THESIS_INVALID
    assert alert.level == AlertLevel.ORANGE


def test_map_event_stop_loss_red():
    event = {"symbol": "300104", "name": "乐视网", "signal_type": "stop_loss", "advice": "止损"}
    alert = map_event_to_alert("u1", "events:exit:sell_signal", event)
    assert alert.alert_type == AlertType.STOP_LOSS
    assert alert.level == AlertLevel.RED


@pytest.mark.asyncio
async def test_dedup_blocks_within_window(session_factory):
    deduper = AlertDeduper(session_factory, window_seconds=3600)
    alert = Alert.new(
        user_id="u1",
        alert_type=AlertType.REJECT,
        symbol="600519",
        name="贵州茅台",
        message="m",
    )

    from apps.copilot.services.alerts.models import AlertLog

    async with session_factory() as session:
        session.add(
            AlertLog(
                alert_id="prev-1",
                user_id="u1",
                level="red",
                alert_type=AlertType.REJECT.value,
                symbol="600519",
                name="贵州茅台",
                message="历史",
                payload={},
                dedup_key=alert.dedup_key,
                channels_sent={},
                sla_met=None,
                latency_ms=None,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        await session.commit()

    assert await deduper.is_duplicate(alert) is True


@pytest.mark.asyncio
async def test_dedup_passes_outside_window(session_factory):
    deduper = AlertDeduper(session_factory, window_seconds=60)
    alert = Alert.new(
        user_id="u1",
        alert_type=AlertType.REJECT,
        symbol="600519",
        name="贵州茅台",
        message="m",
    )
    assert await deduper.is_duplicate(alert) is False


@pytest.mark.asyncio
async def test_dispatcher_end_to_end_records_sla(session_factory, monkeypatch):
    ch_ok = AsyncMock()
    ch_ok.name = "wechat"
    ch_ok.send.return_value = ChannelResult(
        channel="wechat", ok=True, sent_at=datetime.now(timezone.utc)
    )
    ch_fail = AsyncMock()
    ch_fail.name = "telegram"
    ch_fail.send.return_value = ChannelResult(
        channel="telegram", ok=False, reason="[STUB] missing_token",
    )

    deduper = AlertDeduper(session_factory, window_seconds=3600)
    sla = SLAMonitor(session_factory, red_sla_seconds=300)
    dispatcher = AlertDispatcher(
        redis=None,
        session_factory=session_factory,
        channels=[ch_ok, ch_fail],
        deduper=deduper,
        sla_monitor=sla,
    )

    alert = Alert.new(
        user_id="u1",
        alert_type=AlertType.STOP_LOSS,
        symbol="300104",
        name="乐视网",
        message="止损",
    )
    result = await dispatcher.dispatch(alert)
    assert "wechat" in result and result["wechat"]["ok"] is True
    assert result["telegram"]["ok"] is False

    from sqlalchemy import select

    from apps.copilot.services.alerts.models import AlertLog

    async with session_factory() as session:
        row = (
            await session.execute(select(AlertLog).where(AlertLog.alert_id == alert.alert_id))
        ).scalar_one()
    assert row.sla_met is True
    assert row.latency_ms is not None
    assert row.latency_ms < 5000


@pytest.mark.asyncio
async def test_dispatcher_second_call_is_dedup(session_factory):
    ch = AsyncMock()
    ch.name = "wechat"
    ch.send.return_value = ChannelResult(
        channel="wechat", ok=True, sent_at=datetime.now(timezone.utc)
    )
    deduper = AlertDeduper(session_factory, window_seconds=3600)
    sla = SLAMonitor(session_factory, red_sla_seconds=300)
    dispatcher = AlertDispatcher(None, session_factory, [ch], deduper, sla)

    alert1 = Alert.new(
        user_id="u1", alert_type=AlertType.REJECT, symbol="002450", name="康得新", message="m"
    )
    alert2 = Alert.new(
        user_id="u1", alert_type=AlertType.REJECT, symbol="002450", name="康得新", message="m"
    )
    await dispatcher.dispatch(alert1)
    res2 = await dispatcher.dispatch(alert2)
    assert res2 == {"dedup": True}


@pytest.mark.asyncio
async def test_wechat_channel_stub_when_no_url():
    ch = WechatChannel(webhook_url=None)
    alert = Alert.new(user_id="u1", alert_type=AlertType.REJECT, symbol="x", name="y", message="z")
    res = await ch.send(alert)
    assert res.ok is False
    assert "[STUB]" in res.reason


@pytest.mark.asyncio
async def test_telegram_channel_stub_when_no_token():
    ch = TelegramChannel(bot_token=None, chat_id=None)
    alert = Alert.new(user_id="u1", alert_type=AlertType.DEGRADE, symbol="x", name="y", message="z")
    res = await ch.send(alert)
    assert res.ok is False
    assert "[STUB]" in res.reason


@pytest.mark.asyncio
async def test_email_channel_stub_when_no_credentials():
    ch = EmailChannel(
        host="smtp",
        port=587,
        username=None,
        password=None,
        sender="a@b",
        recipient=None,
    )
    alert = Alert.new(
        user_id="u1", alert_type=AlertType.HEALTH_DROP, symbol="x", name="y", message="z"
    )
    res = await ch.send(alert)
    assert res.ok is False
    assert "[STUB]" in res.reason
