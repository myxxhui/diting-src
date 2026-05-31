"""SQLAlchemy ORM 模型 - 启动期 copilot schema。

表：users / holdings / value_snapshots / event_logs / health_records / thesis_cards / user_decisions / daily_reports / weekly_reports

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.copilot.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    holdings: Mapped[list["Holding"]] = relationship(back_populates="user")


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_pk: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("user_pk", "symbol", name="uq_user_symbol"),
        Index("ix_holdings_symbol", "symbol"),
    )


class ValueSnapshot(Base):
    """组合价值快照（每日一行，账本/SCS 计算基础）。"""

    __tablename__ = "value_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_pk: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detail_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_pk", "snapshot_date", name="uq_user_snapshot"),
    )


class EventLog(Base):
    """上游事件原始日志，按 stream key + msg_id 唯一。"""

    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_key: Mapped[str] = mapped_column(String(128), nullable=False)
    msg_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("stream_key", "msg_id", name="uq_stream_msg"),
        Index("ix_event_logs_stream_received", "stream_key", "received_at"),
    )


class HealthRecord(Base):
    """单次 health_change 事件的快照（M1 体检报告的数据源）。

    [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
    """

    __tablename__ = "health_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    old_health: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    new_health: Mapped[float] = mapped_column(Float, nullable=False)
    health_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    push_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    node_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_health_event"),
        Index("ix_health_symbol_received", "symbol", "received_at"),
    )


class ThesisCard(Base):
    """thesis 卡 - 5 必填字段全部入库。

    [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
    """

    __tablename__ = "thesis_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thesis_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    thesis_summary: Mapped[str] = mapped_column(String(2048), nullable=False)
    evidence_chain: Mapped[list] = mapped_column(JSON, nullable=False)
    risks: Mapped[list] = mapped_column(JSON, nullable=False)
    valuation_anchor: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    pass_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    proposed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_thesis_symbol_proposed", "symbol", "proposed_at"),)


class UserDecision(Base):
    """用户对 thesis 卡的 3 选 1 决策。"""

    __tablename__ = "user_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_pk: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    thesis_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("user_pk", "thesis_id", name="uq_user_thesis"),)


class DailyReport(Base):
    """日报持久化。

    [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
    """

    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "report_date", name="uq_daily_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    html_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WeeklyReport(Base):
    """周报持久化。

    [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
    """

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "iso_year", "iso_week", name="uq_weekly_user_isoweek"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    html_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    """熔断等治理动作审计。

    [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ─── M6 行情解析与规划工作台（step_12）────────────────────────────────────────


class Campaign(Base):
    """作战计划 Campaign。

    [Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md §3.3]
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theme: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planning"
    )  # planning | executing | archived
    funnel_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="radar_intake"
    )  # radar_intake | roadmap | planning | executing | archived
    horizon_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    symbols: Mapped[list["CampaignSymbol"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    nodes: Mapped[list["CampaignNode"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    timeline: Mapped[list["CampaignTimeline"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    monitors: Mapped[list["MonitorSubscription"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignSymbol(Base):
    """Campaign 标的档案（6 维分析档案载体）。"""

    __tablename__ = "campaign_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    graph_position: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 漏斗单一状态机：radar_intake → roadmap → planning → executing → archived
    # [Ref: 25_四区漏斗 · 标的级漏斗重构]
    funnel_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planning", index=True
    )
    is_executing_point: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    promoted_from_candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="symbols")

    # 标的级漏斗：symbol 全局唯一（一个标的 = 一条贯穿四区的 funnel 记录）
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_funnel_symbol"),
    )


class CampaignNode(Base):
    """动作链节点（全 advisory）。"""

    __tablename__ = "campaign_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_condition: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    advice_action: Mapped[str] = mapped_column(String(512), nullable=False)
    execute_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="advisory")
    human_confirmation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planning"
    )  # planning|pending|triggered|executed|skipped
    planned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="nodes")


class CampaignTimeline(Base):
    """利好爆发时间线（step_15 扩展 window/sequence/feasibility）。"""

    __tablename__ = "campaign_timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    window_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    build_lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    sequence_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_weight_pct: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="catalyst")
    confirm_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="inferred"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="expected")
    feasibility_flags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    advisories: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="timeline")


class MonitorSubscription(Base):
    """三支柱监控订阅：moat / catalyst / risk / regime（step_15 长周期巡检）。"""

    __tablename__ = "monitor_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    pillar: Mapped[str] = mapped_column(String(16), nullable=False)  # moat|catalyst|risk|regime
    falsify_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    hypothesis: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    indicator: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    verdict: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # ok|warn|alert|pending
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    evidence_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="monitors")

    __table_args__ = (
        Index("ix_monitor_campaign_pillar", "campaign_id", "pillar"),
    )


class Watchlist(Base):
    """关注清单（雷达/手工加入）。"""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    theme: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    plan_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entry_plan: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    added_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("symbol", name="uq_watchlist_symbol"),)


# ─── M8 行情雷达 + 三段流水线（step_14）────────────────────────────────────────


class StageArtifact(Base):
    """单工作区内 T0/T1/T2 段级审计产物。

    [Ref: 25_四区漏斗_三段流水线_架构脊柱_设计.md §3.2]
    """

    __tablename__ = "stage_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    scan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    workspace: Mapped[str] = mapped_column(String(32), nullable=False, default="radar")
    stage: Mapped[str] = mapped_column(String(32), nullable=False)  # T0_raw|T1_distilled|T2_verdict
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_ver: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    engine_ver: Mapped[str] = mapped_column(String(32), nullable=False, default="step14")
    input_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class WorkspaceArtifact(Base):
    """工作区对外精简关键数据集（= 本区 T2 对外视图）。"""

    __tablename__ = "workspace_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    scan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    workspace: Mapped[str] = mapped_column(String(32), nullable=False, default="radar")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    key_facts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    verdict: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upstream_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    t2_artifact_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ModelProfile(Base):
    """模型路由配置（workspace + task → tier/model_id）。"""

    __tablename__ = "model_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace: Mapped[str] = mapped_column(String(32), nullable=False)
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    override_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("workspace", "task", name="uq_model_profile_ws_task"),
    )


class RadarScan(Base):
    """一次雷达扫描会话。"""

    __tablename__ = "radar_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_type: Mapped[str] = mapped_column(String(32), nullable=False)  # hot_industry|concept|symbol
    query_text: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running"
    )  # running|done|failed
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    candidates: Mapped[list["RadarCandidate"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class RadarCandidate(Base):
    """雷达候选标的全方位评估快照。"""

    __tablename__ = "radar_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("radar_scans.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    concept: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    niche_text: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    value_chain_pos: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    is_leader: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    leader_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    moat_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    profit_quality: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    market_phase: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    catalyst_window: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    risk_summary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    scan: Mapped["RadarScan"] = relationship(back_populates="candidates")


# ─── M9 滚动路线图双层锚定（step_15）────────────────────────────────────────────


class ExecutionAdvice(Base):
    """执行区仓位指导快照（全 advisory，绝不下单）。

    [Ref: step_17_执行中仓位指导.md §3 §3.1]
    """

    __tablename__ = "execution_advices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unrealized_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    advice_action: Mapped[str] = mapped_column(String(64), nullable=False, default="持有")
    rationale: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    evidence_chain: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    safety_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    execute_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="advisory"
    )
    human_confirmation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    as_of: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    campaign: Mapped["Campaign"] = relationship()


class RegimeAssessment(Base):
    """行情生命周期判定（启动期全 inferred）。"""

    __tablename__ = "regime_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon_class: Mapped[str] = mapped_column(
        String(32), nullable=False, default="single"
    )  # single|short|mid|long_multiwave
    wave_count_est: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_est: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirm_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="inferred"
    )
    proxy_sources: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    next_wave_window: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("campaign_id", "symbol", name="uq_regime_campaign_symbol"),
    )
