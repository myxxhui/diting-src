"""health_change 处理器幂等性测试。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
"""
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import EventLog, HealthRecord
from apps.copilot.events.handlers.health_change import handle_health_change


def _payload(symbol="600519", push_level=3):
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "health_change",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "name": "贵州茅台",
        "old_health": 90.0,
        "new_health": 67.0,
        "health_delta": -23.0,
        "push_level": push_level,
        "change_reason": "test",
        "node_state": {"state": "warning"},
    }


def test_handler_writes_two_tables():
    async def _run():
        await init_db()
        async with AsyncSessionLocal() as s:
            await handle_health_change(s, _payload(), msg_id="1-0")
            hr = await s.scalar(select(func.count(HealthRecord.id)))
            el = await s.scalar(select(func.count(EventLog.id)))
            return hr, el

    hr, el = asyncio.run(_run())
    assert hr == 1 and el == 1


def test_handler_idempotent_on_same_event_id():
    async def _run():
        await init_db()
        async with AsyncSessionLocal() as s:
            p = _payload()
            await handle_health_change(s, p, msg_id="1-0")
            await handle_health_change(s, p, msg_id="1-1")
            return await s.scalar(select(func.count(HealthRecord.id)))

    assert asyncio.run(_run()) == 1
