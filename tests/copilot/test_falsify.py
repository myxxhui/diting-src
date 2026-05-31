"""M10 规划中证伪与持续监控 pytest。

[Ref: step_16 · 24_ §9 ⑨]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol, HealthRecord, StageArtifact
from apps.copilot.main import app
from apps.copilot.modules.planning.falsify import (
    FALSIFY_TYPES,
    _eval_falsify_catalyst,
    _eval_falsify_moat,
    compute_readiness,
    ensure_default_falsify_tasks,
    refresh_falsify_verdicts,
)


@pytest.fixture(autouse=True)
def _planning_fake_redis(monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        for mod in (
            "apps.copilot.routers.planning_routes",
            "apps.copilot.services.redis_wait",
            "apps.copilot.modules.planning.service",
        ):
            monkeypatch.setattr(f"{mod}.wait_for_sync_redis", _fake_wait)
        yield fake
    except ImportError:
        yield None


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_falsify_types_complete():
    assert FALSIFY_TYPES == frozenset({"moat", "niche", "catalyst", "risk"})


@pytest.mark.asyncio
async def test_ensure_default_four_tasks():
    cid = await _make_campaign_with_symbol()
    async with AsyncSessionLocal() as session:
        subs = await ensure_default_falsify_tasks(session, cid, "601138")
        await session.commit()
        assert len(subs) == 4
        types = {s.falsify_type for s in subs}
        assert types == set(FALSIFY_TYPES)


def test_create_falsify_task_invalid_type(client):
    client.post("/api/campaigns/import-portfolio")
    camps = client.get("/api/campaigns").json()
    cid = camps[0]["id"]
    r = client.post(
        f"/api/campaigns/{cid}/falsify",
        data={"symbol": "601138", "falsify_type": "invalid"},
    )
    assert r.status_code == 400


def test_moat_pending_without_dict(_planning_fake_redis):
    v, ev, payload = _eval_falsify_moat(_planning_fake_redis, "601138", "test")
    assert v == "pending"
    assert payload.get("reason") == "no_monitor_dict"


def _seed_monitor_dict(redis, symbol: str) -> None:
    field_id = "f_moat_test"
    redis.set(
        f"monitor:{symbol}:dict:_meta",
        json.dumps({"count": 1, "industry_chain_summary": "AI服务器"}),
    )
    redis.set(
        f"monitor:{symbol}:dict:{field_id}",
        json.dumps(
            {
                "field_id": field_id,
                "probe_id": "P5",
                "metric_name": "招标命中",
                "symbol": symbol,
                "mapped_logic_chain_nodes": ["GPU"],
                "status": "active",
            }
        ),
    )
    redis.set(
        f"monitor:{symbol}:dict:{field_id}",
        json.dumps(
            {
                "field_id": field_id,
                "probe_id": "P5",
                "metric_name": "招标命中",
                "symbol": symbol,
                "mapped_logic_chain_nodes": ["GPU"],
                "status": "active",
            }
        ),
    )


async def _make_campaign_with_symbol() -> int:
    await init_db()
    async with AsyncSessionLocal() as session:
        camp = Campaign(theme="falsify-test", status="planning", funnel_stage="planning")
        session.add(camp)
        await session.flush()
        session.add(
            CampaignSymbol(
                campaign_id=camp.id,
                symbol="601138",
                name="工业富联",
                analysis_snapshot={"assessment": {"moat": "strong", "niche": "AI服务器"}},
            )
        )
        await session.commit()
        return camp.id


def test_moat_ok_with_hit(_planning_fake_redis):
    sym = "601138"
    _seed_monitor_dict(_planning_fake_redis, sym)
    from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

    reader = MonitorDictReader(_planning_fake_redis)
    field = reader.fields_for_probe(sym, "P5")[0]
    _planning_fake_redis.set(
        field.raw_key,
        json.dumps({"last_hit_at": datetime.now(timezone.utc).isoformat(), **json.loads(_planning_fake_redis.get(field.raw_key))}),
    )
    v, ev, payload = _eval_falsify_moat(_planning_fake_redis, sym, "壁垒")
    assert v == "ok"
    assert payload.get("hits")


def test_catalyst_alert_on_falsified(_planning_fake_redis):
    _planning_fake_redis.xadd(
        "events:thrust:thesis_proposed",
        {
            "json": json.dumps(
                {"symbol": "601138", "action": "falsified", "event_id": "e1"}
            )
        },
    )
    v, ev, payload = _eval_falsify_catalyst(_planning_fake_redis, "601138", "利好")
    assert v == "alert"
    assert payload.get("verdict") == "alert"


def test_compute_readiness_empty():
    r = compute_readiness([])
    assert r["total"] == 0
    assert r["ready_for_executing"] is False


def test_compute_readiness_blocks_on_alert():
    tasks = [
        {"falsify_type": "moat", "verdict": "ok"},
        {"falsify_type": "risk", "verdict": "alert"},
    ]
    r = compute_readiness(tasks)
    assert r["falsified"] == 1
    assert r["ready_for_executing"] is False


def test_compute_readiness_ok_when_threshold_met():
    tasks = [{"falsify_type": t, "verdict": "ok"} for t in FALSIFY_TYPES]
    r = compute_readiness(tasks)
    assert r["ok_rate"] == 1.0
    assert r["ready_for_executing"] is True


def test_promote_executing_requires_human(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.post(f"/api/campaigns/{cid}/promote-executing", data={})
    assert r.status_code == 400
    assert "human_confirmation" in r.json()["detail"]


def test_promote_executing_with_confirm(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    # 标的级漏斗：不带 symbol → 批量晋级该容器全部 planning/roadmap 标的
    r = client.post(
        f"/api/campaigns/{cid}/promote-executing",
        data={"human_confirmed": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["funnel_stage"] == "executing"
    assert len(body["promoted_symbols"]) >= 1
    assert body["human_confirmation_required"] is True
    assert "readiness" in body


def test_cognitive_snapshot_api(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.get(f"/api/campaigns/{cid}/cognitive/601138")
    assert r.status_code == 200
    assert r.json()["symbol"] == "601138"


def test_readiness_api(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.get(f"/api/campaigns/{cid}/readiness")
    assert r.status_code == 200
    assert "advice" in r.json()
    assert r.json()["human_confirmation_required"] is True


@pytest.mark.asyncio
async def test_refresh_writes_planning_artifact(_planning_fake_redis):
    cid = await _make_campaign_with_symbol()
    async with AsyncSessionLocal() as session:
        await ensure_default_falsify_tasks(session, cid, "601138")
        session.add(
            HealthRecord(
                symbol="601138",
                name="工业富联",
                event_id="test-ev-1",
                old_health=0.9,
                new_health=0.85,
                push_level=1,
                change_reason="test",
                occurred_at=datetime.utcnow(),
                received_at=datetime.utcnow(),
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        n = await refresh_falsify_verdicts(session, cid, _planning_fake_redis)
        await session.commit()
        assert n >= 0
        arts = list(
            await session.scalars(
                select(StageArtifact).where(
                    StageArtifact.workspace == "planning",
                    StageArtifact.stage.like("falsify_%"),
                )
            )
        )
        assert len(arts) >= 1


def test_dossier_includes_falsify(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.get(f"/api/campaigns/{cid}/symbols/601138")
    assert r.status_code == 200
    body = r.json()
    assert "falsify_tasks" in body
    assert "readiness" in body
    assert "cognitive_snapshot" in body


def test_post_falsify_creates_task(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.post(
        f"/api/campaigns/{cid}/falsify",
        data={
            "symbol": "601138",
            "falsify_type": "moat",
            "hypothesis": "自定义壁垒论点",
        },
    )
    assert r.status_code == 201
    tasks = client.get(f"/api/campaigns/{cid}/falsify").json()
    hyps = [t["hypothesis"] for t in tasks if t.get("hypothesis") == "自定义壁垒论点"]
    assert hyps
