"""Lighthouse-Alpha 五场景输入/输出 Pydantic schema。

严格对齐：
  - PRD §2.3（Scorer 三维：policy_tier / industry_space / a_share_mapping）
  - PRD §3.3（Architect monitor_matrix · HS Code / source_url / keywords）
  - PRD §3.4（Timer 三段 · incubation / main_wave / retreat）
  - L3 D2 step_03 §3.5.4（Critic 物理证伪 LC1~LC6）

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_02 §3.5.5]
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ==============================================================================
# 通用：调用元数据
# ==============================================================================

class CallMetadata(BaseModel):
    """大模型调用元数据，写入审计 reasons_json。"""

    model_name: str
    prompt_template_id: str
    generated_at: datetime
    tokens_in: int = 0
    tokens_out: int = 0
    cost_yuan_est: float = 0.0
    route: Literal["remote", "local", "mock"] = "mock"


# ==============================================================================
# The Sniffer — 主题嗅探
# ==============================================================================

class SnifferInput(BaseModel):
    """单次嗅探输入：批量原文 + 时间窗口。"""

    raw_texts: list[str] = Field(min_length=1, description="待嗅探的原文片段集合")
    window_start: date
    window_end: date
    source_hint: Optional[Literal["ccgp", "research", "policy", "overseas"]] = None


class SnifferCluster(BaseModel):
    """嗅探输出：候选题材簇。"""

    cluster_id: str = Field(description="md5(keyword + window_start)[:12]")
    keyword: str = Field(min_length=2, description="题材关键词")
    summary: str = Field(min_length=4, description="≥4 字一句话描述（中文允许较短）")
    freq_growth_pct: float = Field(ge=0.0, description="关键词频环比涨幅，0.30 = 30%")
    confidence: float = Field(ge=0.0, le=1.0)
    sample_doc_idx: list[int] = Field(default_factory=list)


class SnifferOutput(BaseModel):
    clusters: list[SnifferCluster] = Field(default_factory=list)
    total_docs: int
    metadata: CallMetadata


# ==============================================================================
# The Architect — 论据架构师 → monitor_matrix
# ==============================================================================

class AlertThresholdStruct(BaseModel):
    operator: Literal["gt", "lt", "mom_pct", "yoy_pct", "sum_pct"]
    value: float
    window_days: int = Field(gt=0)


class MonitorField(BaseModel):
    field_id: str
    probe_id: Literal["P5", "P6", "P7"]
    metric_name: str = Field(min_length=2)
    data_source_type: Literal["STRUCT_DATA_API", "WEB_SCRAPING"]
    source_api: Optional[str] = None
    source_url: Optional[str] = None
    specific_target: str = Field(min_length=2, description="如 'HS Code 85176239 → 美国'")
    keywords: list[str] = Field(default_factory=list)
    alert_threshold: str
    alert_threshold_struct: AlertThresholdStruct
    polling_frequency: Literal["daily", "monthly_after_release"]
    mapped_logic_chain_nodes: list[str] = Field(min_length=1)
    status: Literal["active", "stale"] = "active"

    @field_validator("source_api", mode="after")
    @classmethod
    def _api_when_struct(cls, v, info):
        ds_type = info.data.get("data_source_type")
        if ds_type == "STRUCT_DATA_API" and not v:
            raise ValueError("source_api 在 STRUCT_DATA_API 下必填")
        return v

    @field_validator("source_url", mode="after")
    @classmethod
    def _url_when_web(cls, v, info):
        ds_type = info.data.get("data_source_type")
        if ds_type == "WEB_SCRAPING" and not v:
            raise ValueError("source_url 在 WEB_SCRAPING 下必填")
        return v


class ArchitectInput(BaseModel):
    thesis_card_id: str
    target_company: str = Field(min_length=2)
    symbol: str = Field(min_length=6, max_length=6)
    logic_chain_nodes: list[str] = Field(min_length=1, description="thesis 卡片逻辑链节点 id")


class MonitorMatrix(BaseModel):
    thesis_card_id: str
    target_company: str
    symbol: str
    monitor_matrix: list[MonitorField] = Field(min_length=1)
    metadata: CallMetadata


# ==============================================================================
# The Critic — 物理证伪
# ==============================================================================

class CriticInput(BaseModel):
    cluster_id: str
    cluster_keyword: str
    candidate_symbol: Optional[str] = None
    candidate_revenue_base_yuan: Optional[float] = Field(
        default=None, gt=0, description="近 12 月营收基数（元），用于业绩弹性比"
    )
    candidate_order_size_yuan: Optional[float] = Field(
        default=None, ge=0, description="候选订单/产能估算（元）"
    )
    sample_raw_texts: list[str] = Field(default_factory=list)


class CriticOutput(BaseModel):
    """The Critic 2×2 物理证伪矩阵输出。

    四象限：
      - physical_baseline  (是否有可观测物理底线，如招标/产能/出货)
      - financial_baseline (是否有财务佐证：财报/披露)
      - commercial_baseline(是否有商业逻辑闭环：客户/订单)
      - behavioral_baseline(是否有行为佐证：管理层增持/机构买入)
    """

    cluster_id: str
    physical_gate: bool = Field(description="LC1 物理证伪门禁；false 则拦截")
    physical_baseline: bool
    financial_baseline: bool
    commercial_baseline: bool
    behavioral_baseline: bool
    capacity_elasticity_ratio: Optional[float] = Field(
        default=None, ge=0.0, description="LC3 candidate_order_size / revenue_base"
    )
    capacity_elasticity_ok: bool = Field(description="LC3 ≥ 0.05 (5%)")
    falsified_reason: Optional[str] = None
    source_clusters: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list, description="≤3 条原文引用")
    metadata: CallMetadata


# ==============================================================================
# The Scorer — 三维打分
# ==============================================================================

class ScorerInput(BaseModel):
    cluster_id: str
    cluster_keyword: str
    candidate_symbols: list[str] = Field(default_factory=list)
    policy_text_excerpts: list[str] = Field(default_factory=list)
    industry_research_excerpts: list[str] = Field(default_factory=list)
    a_share_mapping_excerpts: list[str] = Field(default_factory=list)


class ScorerOutput(BaseModel):
    cluster_id: str
    policy_tier: int = Field(ge=0, le=10, description="政策级别 0~10")
    industry_space: int = Field(ge=0, le=10, description="产业空间 0~10")
    a_share_mapping: int = Field(ge=0, le=10, description="A 股映射度 0~10")
    composite: float = Field(ge=0.0, le=10.0, description="加权综合")
    decision: Literal["propose", "watch", "discard"]
    confidence_cap: float = Field(ge=0.0, le=1.0)
    source_urls: list[str] = Field(default_factory=list)
    partial: bool = Field(default=False, description="是否降级")
    metadata: CallMetadata

    @classmethod
    def compute_composite(cls, policy_tier: int, industry_space: int, a_share_mapping: int) -> float:
        """权重 0.35 / 0.35 / 0.30（PRD §2.3）。"""
        return round(0.35 * policy_tier + 0.35 * industry_space + 0.30 * a_share_mapping, 2)

    @classmethod
    def derive_decision(cls, composite: float) -> tuple[Literal["propose", "watch", "discard"], float]:
        """三档阈值（L2 §8A.4 严格对齐）。"""
        if composite >= 8.0:
            return "propose", 0.85
        if composite >= 7.0:
            return "watch", 0.70
        return "discard", 0.0


# ==============================================================================
# The Timer — 三段时间窗口
# ==============================================================================

class TimerPhase(BaseModel):
    start_date: date
    end_date: date
    expected_signal: str = Field(min_length=2)
    confidence: float = Field(ge=0.0, le=1.0)


class CycleAnchor(BaseModel):
    cycle_type: Literal[
        "pre_announce_h1",    # 中报预告期（7 月上旬）
        "h1_release",         # 中报披露期（8 月）
        "pre_announce_q3",    # 三季报预告期（10 月上旬）
        "q3_release",         # 三季报披露期（10 月底 / 11 月）
        "annual_pre_announce", # 年报预告期（1-4 月）
        "annual_release",     # 年报披露期（4 月）
    ]
    expected_window: tuple[date, date]
    confidence: float = Field(ge=0.0, le=1.0)


class TimerInput(BaseModel):
    thesis_card_id: str
    symbol: str
    current_date: date
    monitor_alert_triggered_at: Optional[date] = None
    scan_hit_signals: list[str] = Field(default_factory=list)


class TimerOutput(BaseModel):
    thesis_card_id: str
    current_date: date
    incubation: TimerPhase
    main_wave: TimerPhase
    retreat: TimerPhase
    cycle_anchors: list[CycleAnchor] = Field(default_factory=list)
    metadata: CallMetadata
