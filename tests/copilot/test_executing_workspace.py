"""执行中工作区（28_）单测。

[Ref: 28_ §9]
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import ExecutingCollectSymbol, UserPosition
from apps.copilot.main import app
from apps.copilot.modules.executing.profile import PROBE_KEYS
from apps.copilot.modules.executing.t1_build import build_telemetry


@pytest.fixture
async def db_ready():
    await init_db()
    yield


@pytest.mark.asyncio
async def test_probe_keys_count():
    assert len(PROBE_KEYS) == 25


@pytest.mark.asyncio
async def test_position_crud(db_ready):
    async with AsyncSessionLocal() as session:
        from apps.copilot.modules.executing.positions import (
            delete_position,
            upsert_position,
        )

        await upsert_position(
            session,
            {
                "symbol": "601138",
                "name": "工业富联",
                "quantity": 100,
                "cost_price": 50.0,
                "position_pct": 10.0,
                "source": "ui",
            },
        )
        await session.commit()
        row = await session.get(UserPosition, "601138")
        assert row is not None
        assert row.quantity == 100
        await delete_position(session, "601138")
        await session.commit()


@pytest.mark.asyncio
async def test_t1_build_structure():
    raw = {
        "qmt_atr_trailing": {
            "ok": True,
            "payload": {"atr_multiple": 1.2},
            "source": "test",
        }
    }
    tel = build_telemetry(
        "601138",
        as_of=__import__("datetime").date.today(),
        raw_by_key=raw,
        profit_context={"unrealized_pnl_pct": 5.0},
    )
    assert "L3_Business" in tel
    assert "L4_Game" in tel
    assert "qmt_atr_trailing" in tel["L4_Game"]


@pytest.mark.asyncio
async def test_no_auto_execute_rg():
    import shutil
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if not shutil.which("rg"):
        pytest.skip("rg 未安装")
    r = subprocess.run(
        [
            "rg",
            "-i",
            "auto_trade|order_id|webhook_target|立即下单|一键下单",
            "apps/copilot/modules/executing/",
            "apps/copilot/routers/executing_routes.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 or not (r.stdout or "").strip()


@pytest.mark.asyncio
async def test_sync_status_api(db_ready):
    async with AsyncSessionLocal() as session:
        from apps.copilot.modules.executing.universe import upsert_executing_collect

        await upsert_executing_collect(session, "601138")
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/executing/sync-status")
        assert r.status_code == 200
        assert "601138" in r.json().get("collect_symbols", [])
