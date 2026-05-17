"""M4 价值账本测试。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.copilot.db.database import Base
from apps.copilot.services.ledger.attribution import AttributionInput, attribute, classify
from apps.copilot.services.ledger.circuit_breaker import CircuitBreaker
from apps.copilot.services.ledger.ev import EVCalculator
from apps.copilot.services.ledger.models import AttributionRecord, Octant
from apps.copilot.services.ledger.monthly_report import MonthlyReportGenerator
from apps.copilot.services.ledger.response_recorder import UserResponseRecorder
from apps.copilot.services.ledger.scs import SCSCalculator


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    await engine.dispose()


@pytest.mark.parametrize(
    "advice,action,pnl,expected",
    [
        ("buy", "buy", +100.0, Octant.A),
        ("buy", "buy", -100.0, Octant.B),
        ("sell", "sell", +100.0, Octant.C),
        ("sell", "hold", -100.0, Octant.D),
        ("buy", "skip", +100.0, Octant.E),
        ("buy", "skip", -100.0, Octant.F),
        ("sell", "hold", +100.0, Octant.G),
        ("sell", "sell", -100.0, Octant.H),
    ],
)
def test_classify_covers_all_octants(advice, action, pnl, expected):
    assert classify(AttributionInput(advice=advice, action=action, pnl=pnl)) == expected


def test_attribute_scs_and_ev_deltas():
    out = attribute(AttributionInput(advice="buy", action="buy", pnl=200.0))
    assert out.octant == Octant.A
    assert out.scs_delta > 0 and out.ev_delta == 200.0

    out2 = attribute(AttributionInput(advice="sell", action="sell", pnl=-150.0))
    assert out2.octant == Octant.H
    assert out2.scs_delta < 0 and out2.ev_delta == -150.0


@pytest.mark.asyncio
async def test_response_recorder_upsert(factory):
    rec = UserResponseRecorder(factory)
    ts = datetime.now(timezone.utc)
    rid1 = await rec.record_recommendation(
        user_id="u1",
        thesis_id="t1",
        symbol="600519",
        system_advice="buy",
        user_action="consider",
        advice_ts=ts,
    )
    rid2 = await rec.record_recommendation(
        user_id="u1",
        thesis_id="t1",
        symbol="600519",
        system_advice="buy",
        user_action="join",
        advice_ts=ts,
    )
    assert rid1 == rid2


@pytest.mark.asyncio
async def test_response_recorder_alert(factory):
    rec = UserResponseRecorder(factory)
    ts = datetime.now(timezone.utc)
    rid = await rec.record_alert(
        user_id="u1",
        alert_id="a1",
        symbol="300104",
        system_advice="sell",
        user_action="sold",
        advice_ts=ts,
    )
    assert rid > 0


async def _seed_attributions(factory, user_id: str, items: list[tuple[str, float, float]]):
    now = datetime.now(timezone.utc)
    async with factory() as session:
        for i, (octant, scs_delta, ev_delta) in enumerate(items):
            session.add(
                AttributionRecord(
                    response_id=i,
                    user_id=user_id,
                    symbol="x",
                    octant=octant,
                    system_advice="-",
                    user_action="-",
                    result_pnl=ev_delta,
                    scs_delta=scs_delta,
                    ev_delta=ev_delta,
                    attribution_text="",
                    created_at=now - timedelta(minutes=i),
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_scs_clip_and_basic(factory):
    await _seed_attributions(factory, "u1", [("A", 10, 100), ("B", -8, 0), ("C", 10, 50)])
    calc = SCSCalculator(factory)
    res = await calc.calculate(
        user_id="u1",
        start=datetime.now(timezone.utc) - timedelta(hours=1),
        end=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert 0 <= res.score <= 100
    assert res.sample_count == 3


@pytest.mark.asyncio
async def test_ev_split_hedge_gain_cost(factory):
    await _seed_attributions(
        factory,
        "u1",
        [
            ("A", 10, 200),
            ("C", 10, 80),
            ("F", 6, 50),
            ("H", -8, 30),
        ],
    )
    calc = EVCalculator(factory)
    res = await calc.calculate(
        user_id="u1",
        start=datetime.now(timezone.utc) - timedelta(hours=1),
        end=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert res.hedge_value == 130.0
    assert res.gain_value == 200.0
    assert res.cost_value == 30.0
    assert res.total == 300.0


@pytest.mark.asyncio
async def test_monthly_report_generate(factory, tmp_path):
    await _seed_attributions(factory, "u1", [("A", 10, 100), ("B", -8, 50)])
    scs = SCSCalculator(factory)
    ev = EVCalculator(factory)
    gen = MonthlyReportGenerator(
        factory,
        scs,
        ev,
        reports_dir=str(tmp_path),
        template_dir="apps/copilot/templates",
        css_path="apps/copilot/static/css/monthly_report.css",
    )
    today = date.today()
    row = await gen.generate(user_id="u1", year=today.year, month=today.month)
    assert row.scs > 0 and row.pdf_path is not None
    assert row.pdf_path.endswith((".pdf", ".html"))
    assert row.octant_distribution.get("A", 0) == 1


@pytest.mark.asyncio
async def test_circuit_breaker_triggers_when_bh_exceeds_threshold(factory):
    items = [("B", -8, 0) for _ in range(4)] + [("H", -8, 0) for _ in range(4)] + [("A", 10, 100) for _ in range(12)]
    await _seed_attributions(factory, "u1", items)

    notifier = AsyncMock()
    breaker = CircuitBreaker(factory, window_size=20, bh_threshold=0.35, notifier=notifier)
    state = await breaker.evaluate("u1")
    assert state.paused is True
    notifier.assert_awaited_once()


@pytest.mark.asyncio
async def test_circuit_breaker_does_not_trigger_below_threshold(factory):
    items = [("B", -8, 0) for _ in range(2)] + [("H", -8, 0) for _ in range(2)] + [("A", 10, 100) for _ in range(16)]
    await _seed_attributions(factory, "u1", items)
    breaker = CircuitBreaker(factory, window_size=20, bh_threshold=0.35)
    state = await breaker.evaluate("u1")
    assert state.paused is False


@pytest.mark.asyncio
async def test_circuit_breaker_force_resume(factory):
    items = [("B", -8, 0) for _ in range(10)] + [("H", -8, 0) for _ in range(10)]
    await _seed_attributions(factory, "u1", items)
    breaker = CircuitBreaker(factory, window_size=20, bh_threshold=0.35)
    state = await breaker.evaluate("u1")
    assert state.paused is True
    await breaker.force_resume("ops_reset")
    assert await breaker.is_paused() is False
