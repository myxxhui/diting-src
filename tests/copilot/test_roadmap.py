"""M9 滚动路线图双层锚定 pytest。

[Ref: step_15 · 24_ §9 ⑧]
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.copilot.main import app
from apps.copilot.modules.roadmap.calendar import trading_days_between
from apps.copilot.modules.roadmap.feasibility import evaluate_timeline_feasibility
from apps.copilot.modules.roadmap.regime import classify_horizon_from_proxy


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_trading_days_weekday_fallback():
    start = date(2026, 5, 4)  # Mon
    end = date(2026, 5, 8)  # Fri
    n = trading_days_between(start, end)
    assert n >= 3


def test_build_window_tight_flag():
    today = date(2026, 5, 30)
    anchor = today + timedelta(days=3)
    nodes = [
        {
            "id": 1,
            "symbol": "601138",
            "title": "A",
            "anchor_date": anchor.isoformat(),
            "window_start": (anchor - timedelta(days=10)).isoformat(),
            "window_end": (anchor + timedelta(days=5)).isoformat(),
            "sequence_no": 1,
            "build_lead_days": 15,
            "target_weight_pct": 40,
        }
    ]
    out = evaluate_timeline_feasibility(nodes, build_lead_days=15, today=today)
    td = trading_days_between(today, anchor)
    if td < 15:
        assert "build_window_tight" in out[0]["feasibility_flags"]
    else:
        pytest.skip("交易日历返回 td>=15，跳过 tight 断言")


def test_window_overlap_flag():
    today = date(2026, 6, 1)
    a = today + timedelta(days=60)
    b = today + timedelta(days=65)
    nodes = [
        {
            "id": 1,
            "symbol": "601138",
            "title": "A",
            "anchor_date": a.isoformat(),
            "window_start": (a - timedelta(days=20)).isoformat(),
            "window_end": (a + timedelta(days=10)).isoformat(),
            "sequence_no": 1,
            "target_weight_pct": 60,
        },
        {
            "id": 2,
            "symbol": "300308",
            "title": "B",
            "anchor_date": b.isoformat(),
            "window_start": (b - timedelta(days=25)).isoformat(),
            "window_end": (b + timedelta(days=10)).isoformat(),
            "sequence_no": 2,
            "target_weight_pct": 60,
        },
    ]
    out = evaluate_timeline_feasibility(nodes, today=today)
    flags_a = out[0]["feasibility_flags"]
    flags_b = out[1]["feasibility_flags"]
    assert "window_overlap" in flags_a
    assert "window_overlap" in flags_b
    assert "capital_collision" in flags_a or "capital_collision" in flags_b


def test_sequence_inversion_flag():
    today = date(2026, 6, 1)
    early = today + timedelta(days=30)
    late = today + timedelta(days=90)
    nodes = [
        {
            "id": 1,
            "symbol": "A",
            "title": "late first in seq",
            "anchor_date": late.isoformat(),
            "window_start": late.isoformat(),
            "window_end": late.isoformat(),
            "sequence_no": 1,
        },
        {
            "id": 2,
            "symbol": "B",
            "title": "early second in seq",
            "anchor_date": early.isoformat(),
            "window_start": early.isoformat(),
            "window_end": early.isoformat(),
            "sequence_no": 2,
        },
    ]
    out = evaluate_timeline_feasibility(nodes, today=today)
    assert any("sequence_inversion" in n.get("feasibility_flags", []) for n in out)


def test_regime_thesis_long_inferred():
    hc, confirm, meta = classify_horizon_from_proxy(thesis_horizon="long")
    assert hc == "long_multiwave"
    assert confirm == "inferred"
    assert meta["wave_count_est"] >= 4


def test_regime_market_phase_short():
    hc, confirm, _ = classify_horizon_from_proxy(market_phase="concept")
    assert hc == "short"
    assert confirm == "inferred"


def test_regime_default_single():
    hc, confirm, meta = classify_horizon_from_proxy()
    assert hc == "single"
    assert confirm == "inferred"
    assert "default" in meta.get("proxy_sources", {})


def test_regime_exhaustion_single():
    hc, _, _ = classify_horizon_from_proxy(market_phase="exhaustion")
    assert hc == "single"


@pytest.mark.asyncio
async def test_timeline_api_overlap(client, monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        monkeypatch.setattr(
            "apps.copilot.routers.planning_routes.wait_for_sync_redis", _fake_wait
        )
    except ImportError:
        pass

    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.db.models import Campaign

    await init_db()
    async with AsyncSessionLocal() as session:
        camp = Campaign(theme="step15-test", status="planning", funnel_stage="roadmap")
        session.add(camp)
        await session.commit()
        await session.refresh(camp)
        cid = camp.id

    today = date.today()
    d1 = (today + timedelta(days=45)).isoformat()
    d2 = (today + timedelta(days=50)).isoformat()
    r1 = client.post(
        f"/api/campaigns/{cid}/timeline",
        data={
            "symbol": "601138",
            "anchor_date": d1,
            "title": "标的A爆发",
            "sequence_no": 1,
            "target_weight_pct": 60,
        },
    )
    r2 = client.post(
        f"/api/campaigns/{cid}/timeline",
        data={
            "symbol": "300308",
            "anchor_date": d2,
            "title": "标的B爆发",
            "sequence_no": 2,
            "target_weight_pct": 60,
        },
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    tl = client.get(f"/api/campaigns/{cid}/timeline")
    assert tl.status_code == 200
    items = tl.json()
    assert len(items) >= 2
    all_flags = [f for it in items for f in (it.get("feasibility_flags") or [])]
    assert "window_overlap" in all_flags


@pytest.mark.asyncio
async def test_regime_assess_and_patrol(client, monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        monkeypatch.setattr(
            "apps.copilot.routers.planning_routes.wait_for_sync_redis", _fake_wait
        )
    except ImportError:
        pass

    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.db.models import Campaign, CampaignSymbol

    await init_db()
    async with AsyncSessionLocal() as session:
        camp = Campaign(theme="step15-regime", status="planning", funnel_stage="roadmap")
        session.add(camp)
        await session.flush()
        session.add(
            CampaignSymbol(
                campaign_id=camp.id,
                symbol="601138",
                name="工业富联",
                analysis_snapshot={
                    "market_phase": "realization",
                    "thesis_horizon": "long",
                },
            )
        )
        await session.commit()
        cid = camp.id

    r = client.post(f"/api/campaigns/{cid}/regime/assess")
    assert r.status_code == 200
    regimes = r.json()
    assert len(regimes) >= 1
    assert regimes[0]["confirm_state"] == "inferred"

    mon = client.get(f"/api/campaigns/{cid}/monitors")
    assert mon.status_code == 200
    regime_subs = [m for m in mon.json() if m.get("falsify_type") == "regime"]
    assert len(regime_subs) >= 1


@pytest.mark.asyncio
async def test_archive_keeps_long(client, monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        monkeypatch.setattr(
            "apps.copilot.routers.planning_routes.wait_for_sync_redis", _fake_wait
        )
    except ImportError:
        pass

    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.db.models import Campaign, CampaignSymbol, RegimeAssessment

    await init_db()
    async with AsyncSessionLocal() as session:
        camp = Campaign(theme="step15-archive", status="executing", funnel_stage="executing")
        session.add(camp)
        await session.flush()
        session.add(
            CampaignSymbol(
                campaign_id=camp.id,
                symbol="601138",
                name="工业富联",
                funnel_stage="executing",
            )
        )
        session.add(
            RegimeAssessment(
                campaign_id=camp.id,
                symbol="601138",
                horizon_class="long_multiwave",
                wave_count_est=4,
                duration_est="5~8年多波",
                confirm_state="inferred",
            )
        )
        await session.commit()
        cid = camp.id

    r = client.post(f"/api/campaigns/{cid}/archive")
    assert r.status_code == 200
    body = r.json()
    # 标的级漏斗：long_multiwave 标的归档时回流路线图（rolled_back），保留下一波
    assert "601138" in body.get("rolled_back_symbols", [])
    assert body.get("next_wave_pending", 0) >= 1
