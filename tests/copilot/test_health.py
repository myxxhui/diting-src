"""持仓体检模块 pytest（service + API）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
"""
import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import HealthRecord, Holding, User
from apps.copilot.main import app
from apps.copilot.modules.health_check.service import (
    get_dashboard,
    get_detail,
    push_level_to_color,
)


@pytest.mark.parametrize(
    "level, expected",
    [(0, "green"), (1, "yellow"), (2, "orange"), (3, "red"), (5, "red"), (-1, "green")],
)
def test_color_mapping(level, expected):
    assert push_level_to_color(level) == expected


async def _seed():
    await init_db()
    async with AsyncSessionLocal() as s:
        user = User(user_id="default", name="默认用户")
        s.add(user)
        await s.flush()
        s.add_all(
            [
                Holding(
                    user_pk=user.id,
                    symbol="600519",
                    name="贵州茅台",
                    shares=100,
                    cost_price=1800,
                ),
                Holding(
                    user_pk=user.id,
                    symbol="000001",
                    name="平安银行",
                    shares=5000,
                    cost_price=12.5,
                ),
            ]
        )
        s.add(
            HealthRecord(
                symbol="600519",
                name="贵州茅台",
                event_id="e1",
                new_health=88.0,
                health_delta=2.0,
                push_level=0,
                change_reason="稳定",
                occurred_at=datetime.utcnow(),
            )
        )
        s.add(
            HealthRecord(
                symbol="000001",
                name="平安银行",
                event_id="e2",
                new_health=52.0,
                health_delta=-23.0,
                push_level=3,
                change_reason="Q2 业绩不及预期",
                occurred_at=datetime.utcnow(),
            )
        )
        await s.commit()


def test_dashboard_groups_by_color():
    asyncio.run(_seed())

    async def _run():
        async with AsyncSessionLocal() as s:
            return await get_dashboard(s)

    data = asyncio.run(_run())
    assert data["summary"]["total"] == 2
    assert data["summary"]["red"] == 1
    assert data["summary"]["green"] == 1
    red_symbols = [c["symbol"] for c in data["cards"]["red"]]
    assert "000001" in red_symbols


def test_detail_returns_history():
    asyncio.run(_seed())

    async def _run():
        async with AsyncSessionLocal() as s:
            return await get_detail(s, "000001")

    detail = asyncio.run(_run())
    assert detail["symbol"] == "000001"
    assert detail["color"] == "red"
    assert detail["state"] == "exit"
    assert len(detail["history"]) >= 1


def test_api_dashboard_endpoint():
    asyncio.run(_seed())
    with TestClient(app) as client:
        r = client.get("/api/health/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "cards" in body and "summary" in body
        assert body["summary"]["total"] == 2


def test_dashboard_html_renders():
    asyncio.run(_seed())
    with TestClient(app) as client:
        r = client.get("/health-dashboard")
        assert r.status_code == 200
        assert "持仓体检" in r.text
        assert "000001" in r.text or "600519" in r.text


def test_health_returns_ok():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "copilot"
        assert "upstream" in body
        assert len(body["upstream"]) == 7
