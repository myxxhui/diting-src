"""政策 T1 Dispatcher 单元测试。"""
from __future__ import annotations

import asyncio
import json

import pytest

from apps.copilot.services.deepsea.policy_ingest import register_policy_doc
from apps.copilot.services.deepsea.policy_reader import read_policy_sectors_from_pg
from apps.copilot.services.deepsea.policy_t1_dispatcher import (
    classify_direction,
    dispatch_policy_t1,
    infer_doc_t1_snapshot,
    match_sector_hits,
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


def test_classify_direction_tailwind():
    assert classify_direction("关于加快算力基础设施建设的通知") == "tailwind"


def test_classify_direction_headwind():
    assert classify_direction("关于严格限制高耗能产能的整顿通知") == "headwind"


def test_classify_direction_mixed():
    text = "支持人工智能发展，同时严格限制违规产能扩张"
    assert classify_direction(text) == "mixed"


def test_match_sector_hits_expanded_aliases():
    hits = match_sector_hits("印发节能降碳改造攻坚三年行动方案")
    sectors = {h["sector"] for h in hits}
    assert "环保节能" in sectors


def test_match_sector_hits_rejects_weak_finance_noise():
    hits = match_sector_hits("工业和信息化部财务司开展行业走进金融机构第二期行动")
    assert not any(h["sector"] == "金融国资" for h in hits)


def test_match_sector_hits_commercial_satellite_not_defense():
    hits = match_sector_hits("垣信卫星与中国移动手机直连卫星成功发射")
    sectors = {h["sector"] for h in hits}
    assert "军工国防" not in sectors
    assert "商业航天" in sectors


def test_dispatch_t1_full_chain(deepsea_sqlite):
    doc_id = register_policy_doc(
        url="https://www.ndrc.gov.cn/xwdt/tzgg/202606/t20260615_test.html",
        title="关于开展重点行业节能降碳改造攻坚三年行动的通知",
        summary="推动绿色转型与新型储能发展",
        source="ndrc.gov.cn",
        feed_id="ndrc_tzgg",
        published_at=None,
    )
    assert doc_id

    out = dispatch_policy_t1()
    assert out["status"] == "ok"
    assert out["processed"] >= 1

    raw = read_policy_sectors_from_pg(top_n=10)
    assert raw["ok"] is True
    assert raw["source_layer"] == "deepsea_indicator_state:aggregate"
    sectors = {s["sector"] for s in raw["top_sectors"]}
    assert "环保节能" in sectors or "新能源" in sectors
    assert any(s.get("direction") for s in raw["top_sectors"])

    # 幂等：再次 dispatch 不应重复 per-doc 行
    again = dispatch_policy_t1()
    assert again["processed"] == 0


def test_infer_doc_t1_snapshot_structure():
    snap = infer_doc_t1_snapshot(
        title="低空经济试点实施方案",
        summary="推动无人机物流与通用航空",
        doc_id="00000000-0000-0000-0000-000000000001",
        source="gov.cn",
    )
    assert snap["direction"] == "tailwind"
    assert snap["top_sectors"][0]["sector"] == "低空经济"
    assert snap["t1_source"] == "rule:z0_policy_t1_v1"
