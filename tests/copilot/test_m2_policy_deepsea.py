"""Z0-M2 DeepSea PG 政策支路 · 禁止 OpenSearch。"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from apps.copilot.metrics.collectors.m2_policy_sectors import collect_policy_sector_direction
from apps.copilot.services.deepsea.policy_reader import (
    POLICY_PROBE_KEY,
    read_policy_sectors_from_pg,
    upsert_policy_indicator_state,
)


@pytest.fixture
def deepsea_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "copilot.db"
    monkeypatch.setenv("COPILOT_DB_URL", f"sqlite+aiosqlite:///{db_path}")

    async def _migrate():
        from sqlalchemy.ext.asyncio import create_async_engine

        from apps.copilot.db.migrate_step48 import migrate_step48

        eng = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        await migrate_step48(eng)
        await eng.dispose()

    asyncio.run(_migrate())
    yield db_path


def test_policy_collect_empty_without_data(deepsea_sqlite):
    out = collect_policy_sector_direction()
    assert out["status"] == "error"
    assert "DeepSea PG" in (out.get("detail") or "")
    assert "OpenSearch" not in (out.get("detail") or "")


def test_policy_collect_from_indicator_state(deepsea_sqlite):
    upsert_policy_indicator_state(
        top_sectors=[
            {"sector": "AI算力", "policy_score": 9.0, "hit_count": 2, "direction": "tailwind"},
            {"sector": "半导体", "policy_score": 6.0, "hit_count": 1},
        ],
        evidence=[{"snippet": "算力基础设施规划", "sector": "AI算力"}],
        doc_id=str(uuid.uuid4()),
    )
    raw = read_policy_sectors_from_pg(top_n=5)
    assert raw["ok"] is True
    assert raw["top_sectors"][0]["sector"] == "AI算力"

    out = collect_policy_sector_direction(top_n=5)
    assert out["status"] == "ok"
    assert out["source"].startswith("deepsea:pg:")
    assert out["data"]["probe_key"] == POLICY_PROBE_KEY


def test_synthesize_merges_deepsea_policy():
    from apps.copilot.metrics.synthesizer.wind_scan import synthesize_wind_scan

    metrics = {
        "M.macro.pmi": {"status": "ok", "data": {"pmi": 50.0, "regime": "expansion"}},
        "M.liq.regime_composite": {
            "status": "ok",
            "data": {"liquidity_regime": "mild_inflow", "p0_prime": False, "macro_regime": "expansion"},
        },
        "M.sector.policy_direction": {
            "status": "ok",
            "source": "deepsea:pg:deepsea_indicator_state",
            "data": {
                "top_sectors": [{"sector": "低空经济", "policy_score": 7.0, "hit_count": 1}],
                "evidence": [{"sector": "低空经济", "snippet": "低空经济试点方案"}],
            },
        },
    }
    out = synthesize_wind_scan(metrics)
    assert out["status"] == "ready"
    assert any(c["sector"] == "低空经济" for c in out["candidates"])
