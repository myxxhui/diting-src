"""证据链构建器测试（mock 数据，离线可跑）。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_03_证据链构建器.md]
"""
from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from apps.deep_strike.engines.evidence_builder import EvidenceChainBuilder
from apps.deep_strike.engines.evidence_models import Evidence, EvidenceChain, EvidenceType

SYMBOL = "600519"


def _reload_stack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEP_STRIKE_MOCK", "1")
    import apps.deep_strike.config as cfg
    import apps.deep_strike.db.database as db
    import apps.deep_strike.data.sources.akshare_source as ak

    importlib.reload(cfg)
    importlib.reload(db)
    importlib.reload(ak)
    import apps.deep_strike.data.ingest as ingest_mod

    importlib.reload(ingest_mod)
    return ingest_mod, db


def test_evidence_model_requires_min_length():
    with pytest.raises(ValidationError):
        Evidence(type=EvidenceType.FINANCIAL, source="", content="x")


def test_dedup_eliminates_identical_content():
    e1 = Evidence(type=EvidenceType.FINANCIAL, source="x", content="aaaa")
    e2 = Evidence(type=EvidenceType.FINANCIAL, source="x", content="aaaa")
    out = EvidenceChainBuilder._dedup([e1, e2])
    assert len(out) == 1


def test_evidence_chain_requires_three_items():
    with pytest.raises(ValidationError):
        EvidenceChain(symbol="600519", items=[])


@pytest.mark.asyncio
async def test_build_returns_at_least_3_items(tmp_path, monkeypatch):
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    async def _run() -> EvidenceChain:
        async with db.AsyncSessionLocal() as s:
            return await EvidenceChainBuilder(s).build(SYMBOL)

    chain = await _run()
    assert chain.symbol == SYMBOL
    assert len(chain.items) >= 3
    assert chain.industry_compared is True
    assert chain.timeseries_window_quarters >= 4


@pytest.mark.asyncio
async def test_compute_metrics_outputs_gross_margin_evidence(tmp_path, monkeypatch):
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(SYMBOL)
    fin = [e for e in chain.items if e.type == EvidenceType.FINANCIAL]
    assert any("毛利率" in e.content for e in fin)


@pytest.mark.asyncio
async def test_compare_industry_emits_industry_evidence(tmp_path, monkeypatch):
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(SYMBOL)
        industry = [e for e in chain.items if e.type == EvidenceType.INDUSTRY]
    assert len(industry) >= 1
    assert "中位数" in industry[0].content


@pytest.mark.asyncio
async def test_announcements_become_evidence(tmp_path, monkeypatch):
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(SYMBOL)
        ann = [e for e in chain.items if e.type == EvidenceType.ANNOUNCEMENT]
    assert len(ann) >= 1


@pytest.mark.asyncio
async def test_evidence_persist_to_db(tmp_path, monkeypatch):
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)
    from apps.deep_strike.db.models import EvidenceRecord

    async with db.AsyncSessionLocal() as s:
        await EvidenceChainBuilder(s).build(SYMBOL)
        cnt = await s.scalar(select(func.count(EvidenceRecord.id)).where(EvidenceRecord.symbol == SYMBOL))
    assert cnt is not None and cnt >= 3


@pytest.mark.asyncio
async def test_idempotent_persist_no_duplicates(tmp_path, monkeypatch):
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)
    from apps.deep_strike.db.models import EvidenceRecord

    async with db.AsyncSessionLocal() as s:
        b = EvidenceChainBuilder(s)
        await b.build(SYMBOL)
        first = await s.scalar(select(func.count(EvidenceRecord.id)))
        await b.build(SYMBOL)
        second = await s.scalar(select(func.count(EvidenceRecord.id)))
    assert first == second


# ──────────────────────────────────────────────────────────────────────
# A2: Critic 接入 build() 集成测试
# ──────────────────────────────────────────────────────────────────────


def _make_fake_critic(physical_gate: bool = True, falsified_reason: str | None = None):
    """构造一个 mock TheCritic，不调远程。"""
    from datetime import datetime

    from apps.deep_strike.lighthouse.critic import TheCritic
    from apps.deep_strike.lighthouse.schemas import CallMetadata, CriticOutput

    class _FakeCritic(TheCritic):
        def __init__(self):
            # 不调 super().__init__，跳过 AIDispatcher 依赖
            pass

        def call(self, payload, *, force_route=None):  # type: ignore[override]
            meta = CallMetadata(
                model_name="fake-critic",
                prompt_template_id="the_critic_v1",
                generated_at=datetime.utcnow(),
                route="mock",
            )
            return CriticOutput(
                cluster_id=payload.cluster_id,
                physical_gate=physical_gate,
                physical_baseline=physical_gate,
                financial_baseline=physical_gate,
                commercial_baseline=physical_gate,
                behavioral_baseline=False,
                capacity_elasticity_ratio=0.08 if physical_gate else 0.01,
                capacity_elasticity_ok=physical_gate,
                falsified_reason=falsified_reason,
                source_clusters=[payload.cluster_id],
                evidence_quotes=["中标公告：合同金额 8 亿元（mock 证据）"],
                metadata=meta,
            )

    return _FakeCritic()


@pytest.mark.asyncio
async def test_build_appends_critic_physical_evidence_when_gate_true(tmp_path, monkeypatch):
    """有 cluster 上下文 + critic 注入 → 链中含 type=PHYSICAL 证据（gate=true）。"""
    from apps.deep_strike.lighthouse.schemas import CriticInput

    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    critic = _make_fake_critic(physical_gate=True)
    inputs = [
        CriticInput(
            cluster_id="cl_liquid_cooling",
            cluster_keyword="液冷算力",
            candidate_symbol=SYMBOL,
            candidate_revenue_base_yuan=1e10,
            candidate_order_size_yuan=8e8,
            sample_raw_texts=["液冷中标公告 8 亿"],
        )
    ]

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(
            SYMBOL, critic_inputs=inputs, critic=critic
        )

    physical = [e for e in chain.items if e.type == EvidenceType.PHYSICAL]
    assert len(physical) == 1, "应有且仅有 1 条 PHYSICAL 证据"
    assert "通过" in physical[0].content, "physical_gate=True 时 content 应含「通过」"
    assert physical[0].confidence == pytest.approx(0.9)
    assert physical[0].source.startswith("critic#cl_liquid_cooling")


@pytest.mark.asyncio
async def test_build_appends_critic_physical_evidence_when_gate_false(tmp_path, monkeypatch):
    """gate=false 时 PHYSICAL 证据仍入链（供下游 step_04 过滤），content 含「拦截」。"""
    from apps.deep_strike.lighthouse.schemas import CriticInput

    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    critic = _make_fake_critic(physical_gate=False, falsified_reason="low_elasticity")
    inputs = [
        CriticInput(
            cluster_id="cl_low_elastic",
            cluster_keyword="纯概念",
            candidate_symbol=SYMBOL,
            candidate_revenue_base_yuan=1e10,
            candidate_order_size_yuan=1e7,
            sample_raw_texts=["概念炒作原文"],
        )
    ]

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(
            SYMBOL, critic_inputs=inputs, critic=critic
        )

    physical = [e for e in chain.items if e.type == EvidenceType.PHYSICAL]
    assert len(physical) == 1
    assert "拦截" in physical[0].content, "physical_gate=False 时 content 应含「拦截」"
    assert physical[0].confidence == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_build_persists_physical_evidence_to_db(tmp_path, monkeypatch):
    """PHYSICAL 证据写库（evidence_type='physical'）。"""
    from apps.deep_strike.db.models import EvidenceRecord
    from apps.deep_strike.lighthouse.schemas import CriticInput

    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    critic = _make_fake_critic(physical_gate=True)
    inputs = [
        CriticInput(
            cluster_id="cl_persist",
            cluster_keyword="x",
            candidate_symbol=SYMBOL,
            candidate_revenue_base_yuan=1e10,
            candidate_order_size_yuan=8e8,
            sample_raw_texts=["x"],
        )
    ]

    async with db.AsyncSessionLocal() as s:
        await EvidenceChainBuilder(s).build(SYMBOL, critic_inputs=inputs, critic=critic)
        cnt = await s.scalar(
            select(func.count(EvidenceRecord.id)).where(
                EvidenceRecord.symbol == SYMBOL,
                EvidenceRecord.evidence_type == "physical",
            )
        )
    assert cnt is not None and cnt >= 1


@pytest.mark.asyncio
async def test_build_multiple_clusters_produce_multiple_physical_evidences(tmp_path, monkeypatch):
    """多个 sniffer_cluster → 多条 PHYSICAL 证据（LC1 每簇一条）。"""
    from apps.deep_strike.lighthouse.schemas import CriticInput

    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    critic = _make_fake_critic(physical_gate=True)
    inputs = [
        CriticInput(
            cluster_id=f"cl_{i}",
            cluster_keyword=f"题材{i}",
            candidate_symbol=SYMBOL,
            candidate_revenue_base_yuan=1e10,
            candidate_order_size_yuan=8e8,
            sample_raw_texts=[f"原文{i}"],
        )
        for i in range(3)
    ]

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(
            SYMBOL, critic_inputs=inputs, critic=critic
        )

    physical = [e for e in chain.items if e.type == EvidenceType.PHYSICAL]
    cluster_ids = {e.source for e in physical}
    assert len(cluster_ids) == 3, f"应有 3 个不同 cluster 的 PHYSICAL 证据，实际 {cluster_ids}"


@pytest.mark.asyncio
async def test_build_without_critic_still_works(tmp_path, monkeypatch):
    """未提供 critic 时 build() 行为不变（向后兼容）。"""
    ingest_mod, db = _reload_stack(tmp_path, monkeypatch)
    await ingest_mod.ingest_symbol(SYMBOL)

    async with db.AsyncSessionLocal() as s:
        chain = await EvidenceChainBuilder(s).build(SYMBOL)

    physical = [e for e in chain.items if e.type == EvidenceType.PHYSICAL]
    assert len(physical) == 0, "未注入 critic 时不应出现 PHYSICAL 证据"
