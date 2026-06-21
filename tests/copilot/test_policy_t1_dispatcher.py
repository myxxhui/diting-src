"""政策 T1 Dispatcher 单元测试（v2.1 · 无 fallback · LLM 推断 impl_status）。"""
from __future__ import annotations

import asyncio
import json

import pytest

from apps.copilot.services.deepsea.policy_ingest import register_policy_doc
from apps.copilot.services.deepsea.policy_reader import read_policy_sectors_from_pg
from apps.copilot.services.deepsea.policy_t1_dispatcher import (
    compute_composite_score,
    compute_time_decay_weight,
    dispatch_policy_t1,
    estimate_cost,
    infer_impl_status,
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


# ── §5.1 实施状态推断 ──

def test_infer_impl_status_issued():
    assert infer_impl_status("印发关于加快算力基础设施建设的通知") == "已发布_待执行"


def test_infer_impl_status_draft():
    assert infer_impl_status("关于《人工智能产业发展管理办法（征求意见稿）》公开征求意见的通知") == "征求意见稿"


def test_infer_impl_status_completed():
    assert infer_impl_status("十五五规划编制工作总结报告") == "已执行_完成"


def test_infer_impl_status_abolished():
    assert infer_impl_status("关于废止部分产业政策的决定") == "废止_替代"


def test_infer_impl_status_unknown():
    assert infer_impl_status("某省发改委日常工作动态") == "状态未知"


# ── §5.1 时间衰减 ──

def test_time_decay_L0_within_full_weight():
    w = compute_time_decay_weight("L0", days_since_published=90)
    assert w == 1.0


def test_time_decay_L0_linear_decay():
    w = compute_time_decay_weight("L0", days_since_published=1000)
    assert 0 < w < 1.0


def test_time_decay_L0_beyond_decay():
    w = compute_time_decay_weight("L0", days_since_published=2000)
    assert w == 0.0


def test_time_decay_L2_rapid():
    w = compute_time_decay_weight("L2", days_since_published=90)
    assert w == 0.5


def test_time_decay_L2_expired():
    w = compute_time_decay_weight("L2", days_since_published=200)
    assert w == 0.0


# ── §5.1 三因子评分 ──

def test_compute_composite_score_full_weight():
    score = compute_composite_score(
        impact_score=85.0,
        doc_type="L0",
        impl_status="已发布_待执行",
        days_since_published=10,
    )
    assert score == 85.0


def test_compute_composite_score_draft_half():
    score = compute_composite_score(
        impact_score=80.0,
        doc_type="L1",
        impl_status="征求意见稿",
        days_since_published=10,
    )
    # 80 * 0.7(L1) * 0.5(征求意见稿) * 1.0(时间)
    assert score == 28.0


def test_compute_composite_score_abolished():
    score = compute_composite_score(
        impact_score=90.0,
        doc_type="L0",
        impl_status="废止_替代",
        days_since_published=10,
    )
    # 90 * 1.0 * 0.0 * 1.0 = 0
    assert score == 0.0


def test_compute_composite_score_old_policy():
    score = compute_composite_score(
        impact_score=80.0,
        doc_type="L1",
        impl_status="已发布_待执行",
        days_since_published=500,
    )
    # 80 * 0.7 * 1.0 * (500天衰减后)
    assert 0 < score < 80.0


# ── §7 成本预估算 ──

def test_estimate_cost_empty():
    cost = estimate_cost([], model="deepseek-chat", daily_yuan_budget=5.0)
    assert cost["total_docs"] == 0
    assert cost["est_cost_yuan"] == 0
    assert cost["within_daily_budget"] is True


def test_estimate_cost_within_budget():
    docs = [{"title": "测试", "summary": "测试摘要", "full_text": "X" * 5000}]
    cost = estimate_cost(docs, model="deepseek-chat", daily_yuan_budget=5.0)
    assert cost["total_docs"] == 1
    assert cost["est_cost_yuan"] > 0
    assert cost["within_daily_budget"] is True


def test_estimate_cost_exceed_budget():
    docs = [{"title": "测试", "summary": "测试摘要", "full_text": "X" * 5000}]
    cost = estimate_cost(docs, model="deepseek-chat", daily_yuan_budget=0.0)
    assert cost["within_daily_budget"] is False


# ── §7 无降级：预算超限报 error ──

def test_dispatch_rejects_over_budget(deepsea_sqlite):
    """预算为 0 时直接报 error，不走任何 fallback。"""
    doc_id = register_policy_doc(
        url="https://test.gov.cn/test_over_budget.html",
        title="印发关于加快算力基础设施建设发展的通知",
        summary="推动算力产业高质量发展",
        source="test.gov.cn",
        feed_id="test",
        published_at=None,
    )
    assert doc_id

    import os
    os.environ["POLICY_DAILY_BUDGET"] = "0.0"

    # 注入 0 预算
    from apps.copilot.services.deepsea.policy_t1_dispatcher import _load_llm_config
    import types
    orig_load = _load_llm_config

    def patched_config():
        cfg = orig_load()
        if "cost_control" not in cfg:
            cfg["cost_control"] = {}
        cfg["cost_control"]["daily_yuan_budget"] = 0.0
        return cfg

    dispatcher_module = "apps.copilot.services.deepsea.policy_t1_dispatcher"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"{dispatcher_module}._load_llm_config", patched_config)
        out = dispatch_policy_t1()
        assert out["status"] == "error"
        assert "超日预算" in str(out.get("detail", ""))


# ── 全链集成测试（使用 mock 避免真实 LLM 调用） ──

def test_dispatch_t1_empty_db(deepsea_sqlite):
    """无文档时返回 ok。"""
    out = dispatch_policy_t1(limit=10)
    assert out["status"] == "ok"
    assert out["processed"] == 0


def test_dispatch_t1_pending_without_llm_returns_error(deepsea_sqlite):
    """有待处理文档但 LLM 不可用时报 error（无 fallback）。"""
    doc_id = register_policy_doc(
        url="https://test.gov.cn/test_no_llm.html",
        title="印发关于加快算力基础设施建设发展的通知",
        summary="推动算力产业高质量发展",
        source="test.gov.cn",
        feed_id="test",
        published_at=None,
    )
    assert doc_id

    # mock AI Dispatcher 使其不可用
    from apps.copilot.services.deepsea import policy_t1_llm_scorer

    orig_score = policy_t1_llm_scorer.score_policy_document

    async def mock_failure(*args, **kwargs):
        raise ConnectionError("LLM API 不可用（测试模拟）")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            policy_t1_llm_scorer, "score_policy_document", mock_failure,
        )
        out = dispatch_policy_t1(limit=10)
        assert out["status"] == "error"
        assert out["processed"] == 0
        assert out.get("b1_errors", 0) >= 1


# ── 实施状态在 B2 聚合中的影响 ──

def test_aggregate_draft_lower_than_issued():
    """征求意见稿的综合评分应低于已发布政策。"""
    s1 = compute_composite_score(80, "L0", "已发布_待执行", 10)
    s2 = compute_composite_score(80, "L0", "征求意见稿", 10)
    assert s1 > s2
    assert s2 == 40.0  # 80 * 1.0 * 0.5 * 1.0


def test_aggregate_old_lower_than_new():
    """旧政策的评分应低于新政策。"""
    s1 = compute_composite_score(80, "L1", "已发布_待执行", 30)
    s2 = compute_composite_score(80, "L1", "已发布_待执行", 500)
    assert s1 > s2


# ── §5.0 B1 LLM 推断的 impl_status 优于关键词规则 ──

def test_llm_doc_metadata_multi_policy_weighted():
    """多篇政策加权平均时，impl_status 差异会影响最终评分。"""
    from apps.copilot.services.deepsea.policy_t1_dispatcher import _aggregate_with_decay

    docs = [
        {"doc_id": "test-l0", "title": "正式印发通知", "full_text": "x", "feed_tier": "L0", "published_at": None},
        {"doc_id": "test-draft", "title": "征求意见稿", "full_text": "x", "feed_tier": "L0", "published_at": None},
    ]
    b1_results = [
        {
            "doc_id": "test-l0",
            "sectors": [{"sector_name": "AI算力", "direction": "strong_tailwind", "impact_score": 90, "evidence_quotes": ["x"]}],
            "doc_metadata": {"impl_status": "已发布_待执行", "impl_status_reasoning": "正式印发"},
        },
        {
            "doc_id": "test-draft",
            "sectors": [{"sector_name": "AI算力", "direction": "strong_tailwind", "impact_score": 90, "evidence_quotes": ["x"]}],
            "doc_metadata": {"impl_status": "征求意见稿", "impl_status_reasoning": "公开征求意见"},
        },
    ]
    top, evidence = _aggregate_with_decay(b1_results, docs, top_n=15)
    # L0·已发布=1.0×1.0×1.0, L0·征求意见=1.0×0.5×1.0
    # 加权平均 = (90×1.0 + 90×0.5) / (1.0 + 0.5) = 135/1.5 = 90.0
    # 不加权平均 = (90 + 90) / 2 = 90.0 → 两者恰好相等因为 impact_score 相同
    # 用不同的 impact_score 来验证权重差异：
    b1_diff = [
        {
            "doc_id": "test-l0",
            "sectors": [{"sector_name": "新能源", "direction": "strong_tailwind", "impact_score": 60, "evidence_quotes": ["x"]}],
            "doc_metadata": {"impl_status": "已发布_待执行", "impl_status_reasoning": "x"},
        },
        {
            "doc_id": "test-draft",
            "sectors": [{"sector_name": "新能源", "direction": "weak_tailwind", "impact_score": 100, "evidence_quotes": ["x"]}],
            "doc_metadata": {"impl_status": "征求意见稿", "impl_status_reasoning": "x"},
        },
    ]
    top2, _ = _aggregate_with_decay(b1_diff, docs, top_n=15)
    # 已发布_待执行：60 × 1.0 × 1.0 × 1.0 = 60, weight=1.0
    # 征求意见稿:   100 × 1.0 × 0.5 × 1.0 = 50, weight=0.5
    # 加权平均 = (60 + 50) / (1.0 + 0.5) = 110/1.5 ≈ 73.33
    # 不加权平均 = (60 + 100) / 2 = 80
    # 征求意见稿的高分被打了折扣，更接近"正式印发"的 60
    assert top2[0]["composite_score"] == pytest.approx(73.33, rel=0.01)
