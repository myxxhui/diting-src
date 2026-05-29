"""The Mapper 单元测试：4 档弹性阈值、稀释排雷、ThesisProposedEvent 投递、no-buy 单测。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md §3.5.4 M1~M7]
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.deep_strike.playbooks.the_mapper.mapper import (
    CriticCluster,
    MapperCandidate,
    _classify_market_cap,
    compute_elasticity,
    load_elasticity_thresholds,
    run_mapper,
    segment_filter,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

THRESHOLDS_PATH = (
    Path(__file__).parent.parent.parent
    / "apps"
    / "deep_strike"
    / "configs"
    / "elasticity_thresholds.yaml"
)


def _load() -> dict:
    return load_elasticity_thresholds(THRESHOLDS_PATH)


def _cluster(symbol: str = "000001", elasticity: float | None = 0.08) -> CriticCluster:
    return CriticCluster(
        evidence_id=1,
        symbol=symbol,
        scan_id="20260101",
        cluster_id="test_cluster_001",
        capacity_elasticity_ratio=elasticity,
        raw={"cluster_id": "test_cluster_001", "physical_gate": True},
    )


class MockSession:
    """极简 mock session：scalars 返回空列表，flush/commit 无操作。"""

    def scalars(self, stmt):
        return MagicMock(first=lambda: None, all=lambda: [])

    def add(self, obj):
        pass

    def flush(self):
        pass

    def commit(self):
        pass


class MockPublisher:
    """记录调用但不真正发 Redis。"""

    def __init__(self):
        self.calls: list[dict] = []
        self.pending_count = 0

    def publish_mapper_thesis(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "mock-msg-id-001"


# ---------------------------------------------------------------------------
# 测试 1：elasticity_thresholds.yaml 存在且 4 档可读
# ---------------------------------------------------------------------------


def test_load_thresholds_yaml():
    thresholds = _load()
    tiers = thresholds.get("tiers", {})
    assert set(tiers.keys()) == {"small_cap", "mid_cap", "large_cap", "extra_large"}
    assert tiers["small_cap"]["min_elasticity"] == pytest.approx(0.10)
    assert tiers["extra_large"]["max_market_cap_yuan"] is None


# ---------------------------------------------------------------------------
# 测试 2：small_cap 达标（弹性 ≥ 0.10）→ proposed
# ---------------------------------------------------------------------------


def test_segment_filter_small_cap_pass():
    thresholds = _load()
    cluster = _cluster(elasticity=0.15)
    session = MockSession()

    # 注入市值：4亿（< 50亿 small_cap）
    with patch(
        "apps.deep_strike.playbooks.the_mapper.mapper._estimate_market_cap",
        return_value=4e8,
    ):
        candidate = segment_filter(
            cluster, 0.15, 1e9, symbol="000001", session=session, thresholds=thresholds
        )

    assert candidate.status == "proposed"
    assert candidate.market_cap_tier == "small_cap"
    assert candidate.dropped_reason is None


# ---------------------------------------------------------------------------
# 测试 3：mid_cap 弹性不足（0.03 < 0.05）→ dropped
# ---------------------------------------------------------------------------


def test_segment_filter_mid_cap_fail():
    thresholds = _load()
    cluster = _cluster(elasticity=0.03)
    session = MockSession()

    with patch(
        "apps.deep_strike.playbooks.the_mapper.mapper._estimate_market_cap",
        return_value=8e9,  # 80亿 → mid_cap
    ):
        candidate = segment_filter(
            cluster, 0.03, 5e9, symbol="000001", session=session, thresholds=thresholds
        )

    assert candidate.status == "dropped"
    assert candidate.dropped_reason == "elasticity_below_threshold"


# ---------------------------------------------------------------------------
# 测试 4：large_cap 达标（0.025 ≥ 0.02）→ proposed
# ---------------------------------------------------------------------------


def test_segment_filter_large_cap_pass():
    thresholds = _load()
    cluster = _cluster(elasticity=0.025)
    session = MockSession()

    with patch(
        "apps.deep_strike.playbooks.the_mapper.mapper._estimate_market_cap",
        return_value=5e10,  # 500亿 → large_cap
    ):
        candidate = segment_filter(
            cluster, 0.025, 1e10, symbol="000001", session=session, thresholds=thresholds
        )

    assert candidate.status == "proposed"
    assert candidate.market_cap_tier == "large_cap"


# ---------------------------------------------------------------------------
# 测试 5：extra_large 稀释排雷（M4）- 弹性 < 0.01 → base_dilution
# ---------------------------------------------------------------------------


def test_segment_filter_extra_large_dilution():
    thresholds = _load()
    cluster = _cluster(elasticity=0.005)
    session = MockSession()

    with patch(
        "apps.deep_strike.playbooks.the_mapper.mapper._estimate_market_cap",
        return_value=2e11,  # 2000亿 → extra_large
    ):
        candidate = segment_filter(
            cluster, 0.005, 5e10, symbol="000001", session=session, thresholds=thresholds
        )

    assert candidate.status == "dropped"
    assert candidate.dropped_reason == "base_dilution"


# ---------------------------------------------------------------------------
# 测试 6：弹性比未知 → pending_elasticity（不丢弃，不发事件）
# ---------------------------------------------------------------------------


def test_segment_filter_pending_elasticity():
    thresholds = _load()
    cluster = _cluster(elasticity=None)
    session = MockSession()

    with patch(
        "apps.deep_strike.playbooks.the_mapper.mapper._estimate_market_cap",
        return_value=None,
    ):
        candidate = segment_filter(
            cluster, None, None, symbol="000001", session=session, thresholds=thresholds
        )

    assert candidate.status == "pending_elasticity"
    assert candidate.target_symbol is None


# ---------------------------------------------------------------------------
# 测试 7：run_mapper 发布 ThesisProposedEvent（proposed → 投递）
# ---------------------------------------------------------------------------


def test_run_mapper_emits_event():
    """run_mapper 对 proposed 候选应调 publisher.publish_mapper_thesis。"""
    publisher = MockPublisher()

    def mock_load_clusters(symbol, *, session, scan_id=None):
        return [_cluster(elasticity=0.10)]

    def mock_fetch_revenue(symbol, *, session):
        return 1e9

    with (
        patch(
            "apps.deep_strike.playbooks.the_mapper.mapper.load_critic_passed_clusters",
            side_effect=mock_load_clusters,
        ),
        patch(
            "apps.deep_strike.playbooks.the_mapper.mapper.fetch_revenue_base",
            side_effect=mock_fetch_revenue,
        ),
        patch(
            "apps.deep_strike.playbooks.the_mapper.mapper._estimate_market_cap",
            return_value=8e9,  # mid_cap
        ),
    ):
        session = MockSession()
        result = run_mapper(
            "000001",
            session=session,
            publisher=publisher,
            thresholds_path=THRESHOLDS_PATH,
        )

    assert result.events_emitted >= 1
    assert len(publisher.calls) >= 1
    event = publisher.calls[0]
    # M7: 不含 buy/execute
    assert "buy" not in event
    assert "execute" not in event
    assert event["target_symbol"] == "000001"
    assert event["elasticity_ratio"] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# 测试 8：无 Critic 通过簇时 → 0 事件，不报错
# ---------------------------------------------------------------------------


def test_run_mapper_no_clusters():
    publisher = MockPublisher()

    with patch(
        "apps.deep_strike.playbooks.the_mapper.mapper.load_critic_passed_clusters",
        return_value=[],
    ):
        session = MockSession()
        result = run_mapper(
            "000001",
            session=session,
            publisher=publisher,
            thresholds_path=THRESHOLDS_PATH,
        )

    assert result.total_clusters == 0
    assert result.events_emitted == 0
    assert len(publisher.calls) == 0


# ---------------------------------------------------------------------------
# 测试 9：compute_elasticity - Critic 已算好时直接返回
# ---------------------------------------------------------------------------


def test_compute_elasticity_from_critic():
    cluster = _cluster(elasticity=0.07)
    ratio = compute_elasticity(cluster, trailing_12m_revenue=1e9)
    assert ratio == pytest.approx(0.07)


# ---------------------------------------------------------------------------
# 测试 10：compute_elasticity - Critic 无数据时从 order_size 推算
# ---------------------------------------------------------------------------


def test_compute_elasticity_fallback():
    cluster = CriticCluster(
        evidence_id=2,
        symbol="000002",
        scan_id="20260101",
        cluster_id="cluster_002",
        capacity_elasticity_ratio=None,
        raw={"candidate_order_size_yuan": 5e7},
    )
    ratio = compute_elasticity(cluster, trailing_12m_revenue=5e8)
    assert ratio == pytest.approx(0.10)
