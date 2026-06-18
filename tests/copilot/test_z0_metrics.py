"""Z0 段 A 指标合成与采集单元测试（无网络 · no-mock 路径）。"""
from __future__ import annotations

import pytest

from apps.copilot.metrics.synthesizer.wind_scan import build_p0_snapshot, synthesize_wind_scan


def _metric(mid: str, data: dict) -> dict:
    return {"status": "ok", "metric_id": mid, "data": data, "source": "test"}


def test_synthesize_empty_when_m1_missing():
    out = synthesize_wind_scan({})
    assert out["status"] == "empty"
    assert "M1" in (out.get("blocker") or "")


def test_synthesize_ready_with_m1_m5_m2():
    metrics = {
        "M.macro.pmi": _metric("M.macro.pmi", {"pmi": 50.5, "regime": "expansion"}),
        "M.liq.regime_composite": _metric(
            "M.liq.regime_composite",
            {"liquidity_regime": "mild_inflow", "p0_prime": False, "macro_regime": "expansion"},
        ),
        "M.liq.north_net_20d": _metric("M.liq.north_net_20d", {"net_20d_yi": 10}),
        "M.sector.concept_heat": _metric(
            "M.sector.concept_heat",
            {
                "top_sectors": [
                    {"sector": "AI算力", "change_pct": 3.5},
                    {"sector": "低空经济", "change_pct": 2.1},
                ]
            },
        ),
    }
    out = synthesize_wind_scan(metrics)
    assert out["status"] == "ready"
    assert len(out["candidates"]) >= 2
    assert out["candidates"][0]["wind_score"] >= out["candidates"][1]["wind_score"]
    assert out["advisory_only"] is True


def test_synthesize_ready_with_policy_only():
    metrics = {
        "M.macro.pmi": _metric("M.macro.pmi", {"pmi": 50.5, "regime": "expansion"}),
        "M.liq.regime_composite": _metric(
            "M.liq.regime_composite",
            {"liquidity_regime": "mild_inflow", "p0_prime": False, "macro_regime": "expansion"},
        ),
        "M.sector.policy_direction": _metric(
            "M.sector.policy_direction",
            {
                "top_sectors": [
                    {"sector": "AI算力", "policy_score": 8.0, "hit_count": 2},
                ],
                "evidence": [{"sector": "AI算力", "snippet": "算力基础设施规划"}],
            },
        ),
    }
    out = synthesize_wind_scan(metrics)
    assert out["status"] == "ready"
    assert len(out["candidates"]) >= 1
    assert out["candidates"][0]["sector"] == "AI算力"


def test_p0_snapshot_from_metrics():
    p0 = build_p0_snapshot(
        {
            "M.liq.regime_composite": _metric(
                "M.liq.regime_composite",
                {"liquidity_regime": "risk_off", "p0_prime": True, "macro_regime": "contraction"},
            ),
            "M.macro.pmi": _metric("M.macro.pmi", {"pmi": 48.0, "regime": "contraction"}),
        }
    )
    assert p0["liquidity_regime"] == "risk_off"
    assert p0["p0_prime"] is True


@pytest.mark.asyncio
async def test_run_wind_scan_persists_empty_without_metrics():
    """无采集快照时 wind_scan 应为 empty（不伪造候选）。"""
    from unittest.mock import patch

    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.strategic.z0_workflow import run_wind_scan

    await init_db()
    async with AsyncSessionLocal() as session:
        with patch(
            "apps.copilot.services.redis_wait.wait_for_sync_redis",
            return_value=None,
        ):
            scan = await run_wind_scan(session, redis_client=None)
        await session.commit()
    assert scan["status"] == "empty"
    assert scan["candidates"] == []
