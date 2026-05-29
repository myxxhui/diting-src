"""利润截留扫描仪测试 - 信号 + LangGraph 编排 + API + DB。[Ref: step_04]"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.deep_strike.data.ingest import run as ingest_run
from apps.deep_strike.db.database import AsyncSessionLocal
from apps.deep_strike.db.models import IndustryPeer, ScanLog
from apps.deep_strike.main import app
from apps.deep_strike.playbooks.profit_capture.playbook import ProfitCapturePlaybook
from apps.deep_strike.playbooks.profit_capture.signals.cost_revenue_gap import (
    CostGrowthBelowRevenueSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.gross_margin import (
    GrossMarginQoQUpSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.inventory import (
    InventoryTurnoverUpSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.operating_leverage import (
    OperatingLeverageSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.receivable import (
    ReceivableTurnoverUpSignal,
)
from tests.fixtures.mock_data import build_mock_peers

SYMBOL = "600519"


async def _seed():
    await ingest_run(SYMBOL, mock=True)
    async with AsyncSessionLocal() as s:
        if not await s.scalar(select(func.count(IndustryPeer.id))):
            for r in build_mock_peers(SYMBOL):
                s.add(IndustryPeer(**r))
            await s.commit()


def test_gross_margin_signal_hit_when_qoq_above_2pct():
    r = GrossMarginQoQUpSignal().evaluate({"gross_margin_qoq": 0.025})
    assert r.hit is True
    assert r.value == 0.025


def test_gross_margin_signal_miss_when_below_threshold():
    r = GrossMarginQoQUpSignal().evaluate({"gross_margin_qoq": 0.01})
    assert r.hit is False


def test_gross_margin_signal_none_when_missing():
    r = GrossMarginQoQUpSignal().evaluate({})
    assert r.hit is False
    assert "缺少" in (r.reason or "")


def test_cost_revenue_gap_hit():
    r = CostGrowthBelowRevenueSignal().evaluate(
        {"revenue_growth_yoy": 0.20, "cost_growth_yoy": 0.10}
    )
    assert r.hit is True


def test_operating_leverage_hit():
    r = OperatingLeverageSignal().evaluate(
        {"revenue_growth_yoy": 0.10, "net_profit_growth_yoy": 0.20}
    )
    assert r.hit is True
    assert r.value == pytest.approx(2.0)


def test_operating_leverage_handles_negative_revenue():
    r = OperatingLeverageSignal().evaluate(
        {"revenue_growth_yoy": -0.05, "net_profit_growth_yoy": 0.10}
    )
    assert r.hit is False
    assert "负增长" in (r.reason or "")


def test_receivable_and_inventory_signals():
    assert ReceivableTurnoverUpSignal().evaluate({"receivable_turnover_qoq": 0.1}).hit
    assert InventoryTurnoverUpSignal().evaluate({"inventory_turnover_qoq": 0.1}).hit


def test_full_playbook_returns_propose_for_mock_data():
    asyncio.run(_seed())

    async def _run():
        pb = ProfitCapturePlaybook()
        return await pb.scan(SYMBOL)

    result = asyncio.run(_run())
    assert result.symbol == SYMBOL
    assert result.confidence >= 0.7
    assert result.decision == "propose"
    assert len(result.signals) == 5
    hits = [s for s in result.signals if s.hit]
    assert len(hits) >= 4
    assert len(result.evidence) >= 3


def test_scan_log_written_to_db():
    asyncio.run(_seed())

    async def _run():
        pb = ProfitCapturePlaybook()
        await pb.scan(SYMBOL)
        async with AsyncSessionLocal() as s:
            return await s.scalar(
                select(func.count(ScanLog.id)).where(ScanLog.symbol == SYMBOL)
            )

    cnt = asyncio.run(_run())
    assert cnt >= 1


def test_api_scan_route():
    asyncio.run(_seed())
    with TestClient(app) as client:
        r = client.post("/api/playbooks/profit_capture/scan", json={"symbol": SYMBOL})
        assert r.status_code == 200
        body = r.json()
        assert body["symbol"] == SYMBOL
        assert body["decision"] in ("propose", "watch", "discard")


def test_api_unknown_playbook_404():
    with TestClient(app) as client:
        r = client.post("/api/playbooks/not_exists/scan", json={"symbol": SYMBOL})
        assert r.status_code == 404
