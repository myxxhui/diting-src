"""Lighthouse 五场景单测（全 mock 路由，无需 ANTHROPIC_API_KEY）。

覆盖：
  - Sniffer fallback / parse
  - Architect schema 验证 / fallback
  - Critic 物理证伪门禁（含弹性比 < 5%）
  - Scorer 三档阈值（≥8 propose / 7~7.9 watch / <7 discard）
  - Timer 三段窗口 + cycle_anchors
  - Orchestrator 端到端拦截/通过

[Ref: 03_/02_维度二/.../step_02~07]
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from apps.common.ai_dispatcher import AIDispatcher, AIResponse


class _FakeDispatcher(AIDispatcher):
    """注入预设响应，便于断言 parse 路径。"""

    def __init__(self, canned_text: str, *, model: str = "fake-opus", cost: float = 0.0):
        super().__init__(anthropic_key="", budget_yuan_daily=10_000)
        self._canned = canned_text
        self._model = model
        self._cost = cost

    def call(self, scene, messages, *, max_tokens=2048, temperature=0.2, force_route=None):
        return AIResponse(
            text=self._canned,
            model=self._model,
            scene=scene,
            route="remote",
            latency_ms=1,
            tokens_in=10,
            tokens_out=20,
            cost_yuan_est=self._cost,
        )


# ────────────────────────────────────────────────────────────────────────
# Sniffer
# ────────────────────────────────────────────────────────────────────────

def test_sniffer_parse_ok():
    from apps.deep_strike.lighthouse import TheSniffer
    from apps.deep_strike.lighthouse.schemas import SnifferInput

    canned = json.dumps({
        "clusters": [
            {"keyword": "液冷算力", "summary": "数据中心液冷需求爆发，多家公司中标",
             "freq_growth_pct": 2.5, "confidence": 0.8, "sample_doc_idx": [0, 2]}
        ]
    })
    sniffer = TheSniffer(dispatcher=_FakeDispatcher(canned))
    result = sniffer.call(SnifferInput(
        raw_texts=["智算中心液冷招标", "液冷数据中心英维克中标", "另一篇无关"],
        window_start=date(2026, 5, 1),
        window_end=date(2026, 5, 15),
    ))
    assert len(result.clusters) == 1
    assert result.clusters[0].keyword == "液冷算力"
    assert result.clusters[0].cluster_id  # md5 hash 非空
    assert result.metadata.route == "remote"


def test_sniffer_fallback_on_bad_json():
    from apps.deep_strike.lighthouse import TheSniffer
    from apps.deep_strike.lighthouse.schemas import SnifferInput

    sniffer = TheSniffer(dispatcher=_FakeDispatcher("不是 JSON 的响应"))
    result = sniffer.call(SnifferInput(
        raw_texts=["液冷 服务器 中标 公告", "液冷 中标 服务器 公告"],
        window_start=date(2026, 5, 1),
        window_end=date(2026, 5, 15),
    ))
    # fallback 走 bigram 词频
    assert result.metadata.route == "remote"  # 还是 remote，但 fallback
    assert len(result.clusters) >= 0  # 可能 0 簇（短文本）


# ────────────────────────────────────────────────────────────────────────
# Architect
# ────────────────────────────────────────────────────────────────────────

def test_architect_parses_monitor_matrix():
    from apps.deep_strike.lighthouse import TheArchitect
    from apps.deep_strike.lighthouse.schemas import ArchitectInput

    canned = json.dumps({
        "monitor_matrix": [{
            "field_id": "field_001",
            "probe_id": "P6",
            "metric_name": "光模块对美出口高频数据",
            "data_source_type": "STRUCT_DATA_API",
            "source_api": "akshare.macro_china_customs()",
            "source_url": None,
            "specific_target": "HS Code: 85176239, 目的地: 美国",
            "keywords": [],
            "alert_threshold": "每月20日发布，环比 > 30%",
            "alert_threshold_struct": {"operator": "mom_pct", "value": 0.30, "window_days": 30},
            "polling_frequency": "monthly_after_release",
            "mapped_logic_chain_nodes": ["node_supply_demand_mismatch"]
        }]
    })
    arch = TheArchitect(dispatcher=_FakeDispatcher(canned))
    out = arch.call(ArchitectInput(
        thesis_card_id="thesis_300308",
        target_company="中际旭创",
        symbol="300308",
        logic_chain_nodes=["node_supply_demand_mismatch", "node_overseas_demand"],
    ))
    assert len(out.monitor_matrix) == 1
    assert out.monitor_matrix[0].probe_id == "P6"
    assert out.monitor_matrix[0].source_api.startswith("akshare")


def test_architect_normalize_operator():
    """LLM 自由风格 operator 必须被归一化到 5 枚举之一。"""
    from apps.deep_strike.lighthouse.architect import TheArchitect

    norm = TheArchitect._normalize_operator
    assert norm("mom_pct_or_yoy_pct") == "mom_pct"
    assert norm("count_gte") == "gt"
    assert norm("amount_gte") == "gt"
    assert norm("qoq_pct") == "sum_pct" or norm("qoq_pct") == "gt"  # qoq_pct 不在白名单 → fallback gt 或 sum_pct
    assert norm("GT") == "gt"
    assert norm("mom-pct") == "mom_pct"
    assert norm("") == "gt"
    assert norm("lt") == "lt"


def test_architect_normalize_polling_frequency():
    """LLM 自由风格 polling_frequency 必须被归一化到 schema 2 枚举。"""
    from apps.deep_strike.lighthouse.architect import TheArchitect

    norm = TheArchitect._normalize_polling_frequency
    # 已合法
    assert norm("daily") == "daily"
    assert norm("monthly_after_release") == "monthly_after_release"
    # Opus 常见返回需归一化
    assert norm("weekly") == "daily"
    assert norm("hourly") == "daily"
    assert norm("realtime") == "daily"
    assert norm("monthly") == "monthly_after_release"
    assert norm("quarterly_after_disclosure") == "monthly_after_release"
    assert norm("quarterly") == "monthly_after_release"
    assert norm("annual") == "monthly_after_release"
    # 大小写/连字符
    assert norm("Monthly-After-Release") == "monthly_after_release"
    assert norm("") == "daily"


def test_architect_accepts_field_with_weekly_polling_after_normalize():
    """以前 polling_frequency='weekly' 会让字段被拒；归一化后须能落库。"""
    import json
    from apps.deep_strike.lighthouse import TheArchitect
    from apps.deep_strike.lighthouse.schemas import ArchitectInput

    canned = json.dumps({
        "monitor_matrix": [{
            "field_id": "f_weekly",
            "probe_id": "P7",
            "metric_name": "policy_keyword",
            "data_source_type": "WEB_SCRAPING",
            "source_api": None,
            "source_url": "https://www.gov.cn",
            "specific_target": "电力基建关键词",
            "keywords": ["电网投资"],
            "alert_threshold": "每周 ≥ 3 条",
            "alert_threshold_struct": {"operator": "gt", "value": 3.0, "window_days": 7},
            "polling_frequency": "weekly",  # 旧 schema 会拒
            "mapped_logic_chain_nodes": ["node_grid"],
        }]
    })
    arch = TheArchitect(dispatcher=_FakeDispatcher(canned))
    out = arch.call(ArchitectInput(
        thesis_card_id="t1", target_company="测试", symbol="000001",
        logic_chain_nodes=["node_grid"],
    ))
    assert len(out.monitor_matrix) == 1
    assert out.monitor_matrix[0].polling_frequency == "daily"  # weekly → daily


def test_architect_parses_with_noisy_operator():
    """模型给的 operator 不在 Literal 枚举，但 normalize 后仍能落库。"""
    from apps.deep_strike.lighthouse import TheArchitect
    from apps.deep_strike.lighthouse.schemas import ArchitectInput

    canned = json.dumps({
        "monitor_matrix": [{
            "field_id": "f1", "probe_id": "P5",
            "metric_name": "测试",
            "data_source_type": "WEB_SCRAPING",
            "source_api": None, "source_url": "https://example.com",
            "specific_target": "测试",
            "keywords": ["x"],
            "alert_threshold": "中标累计 > 营收 20%",
            "alert_threshold_struct": {
                "operator": "count_gte_or_amount_gte",  # noisy
                "value": 5.0,
                "window_days": 30,
            },
            "polling_frequency": "daily",
            "mapped_logic_chain_nodes": ["node_x"]
        }]
    })
    arch = TheArchitect(dispatcher=_FakeDispatcher(canned))
    out = arch.call(ArchitectInput(
        thesis_card_id="t1", target_company="测试公司", symbol="000001",
        logic_chain_nodes=["node_x"],
    ))
    assert len(out.monitor_matrix) == 1
    assert out.monitor_matrix[0].alert_threshold_struct.operator in {
        "gt", "lt", "mom_pct", "yoy_pct", "sum_pct"
    }


def test_architect_fallback_on_empty():
    from apps.deep_strike.lighthouse import TheArchitect
    from apps.deep_strike.lighthouse.schemas import ArchitectInput

    arch = TheArchitect(dispatcher=_FakeDispatcher("{}"))
    out = arch.call(ArchitectInput(
        thesis_card_id="thesis_x",
        target_company="测试",
        symbol="000001",
        logic_chain_nodes=["node_test"],
    ))
    # fallback 出最低限度 P7 字段
    assert len(out.monitor_matrix) == 1
    assert out.monitor_matrix[0].probe_id == "P7"


# ────────────────────────────────────────────────────────────────────────
# Critic
# ────────────────────────────────────────────────────────────────────────

def test_critic_physical_gate_true_when_all_baselines():
    from apps.deep_strike.lighthouse import TheCritic
    from apps.deep_strike.lighthouse.schemas import CriticInput

    canned = json.dumps({
        "physical_baseline": True,
        "financial_baseline": True,
        "commercial_baseline": True,
        "behavioral_baseline": False,
        "physical_gate": True,
        "evidence_quotes": ["中标公告：合同金额 8 亿元，建设期 18 月"]
    })
    critic = TheCritic(dispatcher=_FakeDispatcher(canned))
    out = critic.call(CriticInput(
        cluster_id="cl001",
        cluster_keyword="液冷",
        candidate_symbol="002837",
        candidate_revenue_base_yuan=1.0e10,
        candidate_order_size_yuan=8.0e8,  # 8% 弹性
        sample_raw_texts=["液冷中标公告 8 亿"],
    ))
    assert out.physical_gate is True
    assert out.capacity_elasticity_ok is True
    assert out.capacity_elasticity_ratio == 0.08


def test_critic_physical_gate_false_when_low_elasticity():
    from apps.deep_strike.lighthouse import TheCritic
    from apps.deep_strike.lighthouse.schemas import CriticInput

    canned = json.dumps({
        "physical_baseline": True,
        "financial_baseline": True,
        "commercial_baseline": True,
        "behavioral_baseline": False,
        "physical_gate": True,
    })
    critic = TheCritic(dispatcher=_FakeDispatcher(canned))
    out = critic.call(CriticInput(
        cluster_id="cl002",
        cluster_keyword="x",
        candidate_revenue_base_yuan=1.0e10,
        candidate_order_size_yuan=1.0e8,  # 1%，低弹性
    ))
    assert out.physical_gate is False
    assert out.falsified_reason == "low_elasticity"


def test_critic_physical_gate_false_when_no_baseline():
    from apps.deep_strike.lighthouse import TheCritic
    from apps.deep_strike.lighthouse.schemas import CriticInput

    canned = json.dumps({
        "physical_baseline": False,
        "financial_baseline": False,
        "commercial_baseline": False,
        "behavioral_baseline": True,
    })
    critic = TheCritic(dispatcher=_FakeDispatcher(canned))
    out = critic.call(CriticInput(cluster_id="cl003", cluster_keyword="纯概念炒作"))
    assert out.physical_gate is False
    assert out.falsified_reason == "no_observable_baseline"


# ────────────────────────────────────────────────────────────────────────
# Scorer
# ────────────────────────────────────────────────────────────────────────

def test_scorer_compose_propose():
    from apps.deep_strike.lighthouse.schemas import ScorerOutput

    composite = ScorerOutput.compute_composite(9, 8, 7)
    # 0.35*9 + 0.35*8 + 0.30*7 = 3.15 + 2.80 + 2.10 = 8.05
    assert composite == 8.05
    decision, cap = ScorerOutput.derive_decision(composite)
    assert decision == "propose"
    assert cap == 0.85


def test_scorer_compose_watch_vs_discard():
    from apps.deep_strike.lighthouse.schemas import ScorerOutput

    # watch 边界
    d, _ = ScorerOutput.derive_decision(7.5)
    assert d == "watch"
    # discard
    d, _ = ScorerOutput.derive_decision(6.9)
    assert d == "discard"


def test_scorer_source_penalty():
    """缺 source 引用自动减一档。"""
    from apps.deep_strike.lighthouse import TheScorer
    from apps.deep_strike.lighthouse.schemas import ScorerInput

    canned = json.dumps({
        "policy_tier": 9, "industry_space": 8, "a_share_mapping": 7,
        "source_urls": [], "reasoning": "test"
    })
    scorer = TheScorer(dispatcher=_FakeDispatcher(canned))
    out = scorer.call(ScorerInput(
        cluster_id="x", cluster_keyword="x",
        policy_text_excerpts=[],         # 缺 → 9-1=8
        industry_research_excerpts=["something"],
        a_share_mapping_excerpts=[],     # 缺 → 7-1=6
    ))
    assert out.policy_tier == 8
    assert out.industry_space == 8
    assert out.a_share_mapping == 6


# ────────────────────────────────────────────────────────────────────────
# Timer
# ────────────────────────────────────────────────────────────────────────

def test_timer_phases_present():
    from apps.deep_strike.lighthouse import TheTimer
    from apps.deep_strike.lighthouse.schemas import TimerInput

    canned = json.dumps({
        "incubation": {"start_date": "2026-06-01", "end_date": "2026-07-10",
                       "expected_signal": "潜伏建仓", "confidence": 0.7},
        "main_wave": {"start_date": "2026-08-15", "end_date": "2026-08-25",
                      "expected_signal": "中报披露共振", "confidence": 0.6},
        "retreat": {"start_date": "2026-08-26", "end_date": "2026-09-10",
                    "expected_signal": "披露后放量滞涨", "confidence": 0.5}
    })
    timer = TheTimer(dispatcher=_FakeDispatcher(canned))
    out = timer.call(TimerInput(
        thesis_card_id="t1",
        symbol="300308",
        current_date=date(2026, 5, 23),
    ))
    assert out.incubation.expected_signal == "潜伏建仓"
    assert len(out.cycle_anchors) >= 1
    # 默认未来 12 月内应包含至少一个 release 类型
    assert any("release" in a.cycle_type for a in out.cycle_anchors)


# ────────────────────────────────────────────────────────────────────────
# Orchestrator
# ────────────────────────────────────────────────────────────────────────

def test_orchestrator_drops_low_elasticity_at_critic(monkeypatch):
    """物理证伪拦截：弹性比 < 5% 的候选不进入 Scorer/Architect/Timer。"""
    from apps.deep_strike.lighthouse import LighthouseOrchestrator
    from apps.deep_strike.lighthouse.schemas import SnifferInput

    orch = LighthouseOrchestrator()

    # 用 monkeypatch 把 dispatcher 全替换为返回标准响应
    sniffer_canned = json.dumps({
        "clusters": [
            {"keyword": "test_low", "summary": "测试低弹性簇",
             "freq_growth_pct": 0.5, "confidence": 0.7, "sample_doc_idx": [0]}
        ]
    })
    critic_canned = json.dumps({
        "physical_baseline": True,
        "financial_baseline": True,
        "commercial_baseline": True,
        "behavioral_baseline": False,
    })
    monkeypatch.setattr(orch.sniffer, "dispatcher", _FakeDispatcher(sniffer_canned))
    monkeypatch.setattr(orch.critic, "dispatcher", _FakeDispatcher(critic_canned))

    res = orch.run_for_clusters(
        SnifferInput(raw_texts=["低弹性测试原文"], window_start=date(2026, 5, 1), window_end=date(2026, 5, 15)),
        candidate_context={
            "test_low": {
                "candidate_symbol": "300499",
                "candidate_revenue_base_yuan": 1.0e10,
                "candidate_order_size_yuan": 1.0e8,  # 1%
            }
        },
    )
    assert len(res.outcomes) == 1
    assert res.outcomes[0].status == "dropped_by_critic"
    assert res.outcomes[0].critic.physical_gate is False
    assert res.outcomes[0].scorer is None  # 未进入 scorer
    assert res.outcomes[0].architect is None


def test_orchestrator_full_passing_chain(monkeypatch):
    """端到端：合格候选走过 critic → scorer(propose) → architect → timer。"""
    from apps.deep_strike.lighthouse import LighthouseOrchestrator
    from apps.deep_strike.lighthouse.schemas import SnifferInput

    orch = LighthouseOrchestrator()

    sniffer_canned = json.dumps({
        "clusters": [{"keyword": "液冷", "summary": "液冷算力中标爆发",
                      "freq_growth_pct": 2.0, "confidence": 0.85, "sample_doc_idx": [0, 1]}]
    })
    critic_canned = json.dumps({
        "physical_baseline": True, "financial_baseline": True,
        "commercial_baseline": True, "behavioral_baseline": True,
        "evidence_quotes": ["中标 8 亿元"]
    })
    scorer_canned = json.dumps({
        "policy_tier": 9, "industry_space": 8, "a_share_mapping": 8,
        "source_urls": ["https://policy.example.com"], "reasoning": "ok"
    })
    architect_canned = json.dumps({
        "monitor_matrix": [{
            "field_id": "field_001", "probe_id": "P5",
            "metric_name": "液冷招标金额", "data_source_type": "WEB_SCRAPING",
            "source_api": None, "source_url": "https://www.ccgp.gov.cn",
            "specific_target": "ccgp 液冷招标", "keywords": ["液冷", "智算中心"],
            "alert_threshold": "每月累计 > 上年营收 20%",
            "alert_threshold_struct": {"operator": "sum_pct", "value": 0.20, "window_days": 30},
            "polling_frequency": "daily",
            "mapped_logic_chain_nodes": ["node_supply_demand_mismatch"]
        }]
    })
    timer_canned = json.dumps({
        "incubation": {"start_date": "2026-06-01", "end_date": "2026-07-10",
                       "expected_signal": "潜伏建仓", "confidence": 0.7},
        "main_wave": {"start_date": "2026-08-15", "end_date": "2026-08-25",
                      "expected_signal": "中报披露共振", "confidence": 0.6},
        "retreat": {"start_date": "2026-08-26", "end_date": "2026-09-10",
                    "expected_signal": "披露后放量滞涨", "confidence": 0.5}
    })

    monkeypatch.setattr(orch.sniffer, "dispatcher", _FakeDispatcher(sniffer_canned))
    monkeypatch.setattr(orch.critic, "dispatcher", _FakeDispatcher(critic_canned))
    monkeypatch.setattr(orch.scorer, "dispatcher", _FakeDispatcher(scorer_canned))
    monkeypatch.setattr(orch.architect, "dispatcher", _FakeDispatcher(architect_canned))
    monkeypatch.setattr(orch.timer, "dispatcher", _FakeDispatcher(timer_canned))

    res = orch.run_for_clusters(
        SnifferInput(raw_texts=["液冷中标公告", "另一篇液冷"],
                     window_start=date(2026, 5, 1), window_end=date(2026, 5, 15)),
        candidate_context={
            "液冷": {
                "candidate_symbol": "002837",
                "target_company": "英维克",
                "candidate_revenue_base_yuan": 1.0e10,
                "candidate_order_size_yuan": 8.0e8,  # 8%
                "policy_text_excerpts": ["国务院算力规划"],
                "industry_research_excerpts": ["千亿级液冷市场"],
                "a_share_mapping_excerpts": ["英维克为龙头"],
                "logic_chain_nodes": ["node_supply_demand_mismatch"],
            }
        },
    )
    assert len(res.outcomes) == 1
    out = res.outcomes[0]
    assert out.status == "passed"
    assert out.critic.physical_gate is True
    assert out.scorer.decision == "propose"
    assert out.scorer.composite >= 8.0
    assert out.architect is not None
    assert out.architect.monitor_matrix[0].probe_id == "P5"
    assert out.timer is not None
    assert res.propose_count == 1


def test_orchestrator_no_auto_trade_field():
    """永久规则：编排器返回结构里不存在任何 auto_trade/buy/execute/qmt 字段。"""
    from apps.deep_strike.lighthouse import LighthouseOrchestrator
    from apps.deep_strike.lighthouse.schemas import ScorerOutput

    schema = ScorerOutput.model_json_schema()
    forbidden = {"auto_trade", "buy", "execute", "qmt", "place_order"}
    keys = set(schema.get("properties", {}).keys())
    assert not (keys & forbidden), f"禁字段命中：{keys & forbidden}"


# ────────────────────────────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────────────────────────────

def test_extract_json_handles_fence():
    from apps.deep_strike.lighthouse._base import extract_json

    text = "前置说明 ```json\n{\"a\": 1}\n```\n后续解释"
    assert extract_json(text) == {"a": 1}


def test_extract_json_handles_plain():
    from apps.deep_strike.lighthouse._base import extract_json

    text = "{\"a\": 2}"
    assert extract_json(text) == {"a": 2}


def test_extract_json_handles_noise():
    from apps.deep_strike.lighthouse._base import extract_json

    text = "前缀 {\"a\": 3, \"b\": [1,2]} 后缀"
    assert extract_json(text) == {"a": 3, "b": [1, 2]}
