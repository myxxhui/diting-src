"""SQLAlchemy ORM 模型 - 启动期 copilot schema。

表：users / holdings / value_snapshots / event_logs / health_records / thesis_cards / user_decisions / daily_reports / weekly_reports

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from datetime import date, datetime
from uuid import uuid4
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
from sqlalchemy.dialects.postgresql import JSONB

from apps.copilot.db.database import Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


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
    # 前端「移除」：立即从各 Tab 隐藏；后端保留 ui_removed_at 起 7 天后物理清理
    ui_removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

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


class RadarSymbolVersion(Base):
    """雷达单标的 T0~T2 bundle 持久化（文件缓存 24h 同步入库，保留 30 天、每标的最多 7 版）。"""

    __tablename__ = "radar_symbol_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bundle_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    t0_ok_parts: Mapped[int] = mapped_column(Integer, default=0)
    t2_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    cost_yuan: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("symbol", "version_id", name="uq_radar_sym_version"),
    )


class RadarT0CollectSymbol(Base):
    """基础数据采集标的列表 · T0 一次性/定时任务唯一 universe。

    [Ref: 27_行情雷达全链路架构设计优化 §2.1.1]
    """

    __tablename__ = "radar_t0_collect_symbols"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    enrolled_by: Mapped[str] = mapped_column(String(32), nullable=False, default="workbench")
    last_collect_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_collect_job: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_trade_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RadarSectorDaily(Base):
    """T0-2/3 板块动能与资金 · 每股按东财行业日级 UPSERT。

    [Ref: 27_ §2.2 · 28_ §9.2]
    """

    __tablename__ = "radar_sector_daily"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    board_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    board_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pct_chg_3d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_inflow_5d_yi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    momentum_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    flow_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class RadarMarketSentimentDaily(Base):
    """T0-1 全市场情绪日定稿。

    [Ref: 27_ §2.2.1]
    """

    __tablename__ = "radar_market_sentiment_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_turnover_yi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover_vs_prev_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    advance_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    limit_up_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class RadarT0SyncWatermark(Base):
    """T0 CronJob / bootstrap 水位表。

    [Ref: 27_ §2.8.3]
    """

    __tablename__ = "radar_t0_sync_watermarks"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_trade_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    catch_up_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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


# ─── 执行中工作区（28_ · executing workspace）──────────────────────────────────


class UserPosition(Base):
    """执行区持仓真值（前端 CRUD · DB SoT）。

    [Ref: 28_ §5.3]
    """

    __tablename__ = "user_positions"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opened_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="ui")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExecutingCollectSymbol(Base):
    """执行区 T0 采集宇宙 + 标的基础数据（与 user_positions 同步）。

    [Ref: 28_ §4.2 · §5.3]
    """

    __tablename__ = "executing_collect_symbols"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    profile: Mapped[str] = mapped_column(String(32), nullable=False, default="601138")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    funnel_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opened_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExecutingWorkspaceSettings(Base):
    """执行区全局设置（账户可用资金等）。

    [Ref: 28_ §5.3]
    """

    __tablename__ = "executing_workspace_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    available_cash: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExecutingT0SyncWatermark(Base):
    """执行区 T0 job 水位。

    [Ref: 28_ §4.3]
    """

    __tablename__ = "executing_t0_sync_watermarks"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(6), primary_key=True, default="*")
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_trade_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_period_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    catch_up_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ExecutingT0ProbeState(Base):
    """25 探针逐项新鲜度。

    [Ref: 28_ §4.3 §4.5]
    """

    __tablename__ = "executing_t0_probe_state"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    probe_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stale_after: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="missing")
    blocker: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExecutingDailyBar(Base):
    """执行区日线底库 · 腾讯 fqkline 前复权 OHLCV（#15 等 JL4 硬算输入）。

    [Ref: 28_ §2.2.2]
    """

    __tablename__ = "executing_daily_bars"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adjust: Mapped[str] = mapped_column(String(8), primary_key=True, default="qfq")
    open: Mapped[float] = mapped_column(nullable=False)
    high: Mapped[float] = mapped_column(nullable=False)
    low: Mapped[float] = mapped_column(nullable=False)
    close: Mapped[float] = mapped_column(nullable=False)
    volume: Mapped[float] = mapped_column(nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tencent_fqkline")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingMoneyflowDaily(Base):
    """#17 smart_money_flow · Tushare moneyflow 日终聚合底库（目标 250 交易日）。

    [Ref: 28_ §3.2.1]
    """

    __tablename__ = "executing_moneyflow_daily"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    buy_elg_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sell_elg_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    buy_elg_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sell_elg_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    net_elg_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    buy_lg_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sell_lg_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    buy_md_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sell_md_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    buy_sm_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sell_sm_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    net_mf_vol: Mapped[float] = mapped_column(nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="Tushare API (moneyflow)")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingMarginDaily(Base):
    """#19 margin_short_skew · Tushare margin_detail 日终底库（目标 250 交易日）。

    [Ref: 28_ §3.2.3]
    """

    __tablename__ = "executing_margin_daily"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rzye: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rqye: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rzmre: Mapped[float] = mapped_column(nullable=False, default=0.0)
    margin_short_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    free_float_mkt_cap: Mapped[Optional[float]] = mapped_column(nullable=True)
    margin_to_float_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(
        String(96), nullable=False, default="Tushare Margin Detail (T+1 Lag)"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingTurnoverDaily(Base):
    """#20 turnover_acceleration · Tushare daily_basic 自由换手率底库（目标 140 交易日）。

    [Ref: 28_ §3.2.4]
    """

    __tablename__ = "executing_turnover_daily"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    turnover_rate_f: Mapped[float] = mapped_column(nullable=False, default=0.0)
    volume_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(
        String(96), nullable=False, default="Tushare Daily Basic (turnover_rate_f)"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingT0Raw(Base):
    """T0 原始采集落库（按 probe_key 追加）。"""

    __tablename__ = "executing_t0_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    probe_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trade_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    source: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingT1ProbeSnapshot(Base):
    """T1 指标节点最新快照（Redis 之外 PG 可回放 · 与 #15 daily_bars 同级）。

    [Ref: 28_ §4.2 · #16/#17 PG 落库]
    """

    __tablename__ = "executing_t1_probe_snapshots"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    probe_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    node_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    source: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingDailyAudit(Base):
    """T1 telemetry + T2 audit 日快照。"""

    __tablename__ = "executing_daily_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    telemetry_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    audit_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    t2_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ExecutingPipelineRun(Base):
    """交互式 daily-run 进度。"""

    __tablename__ = "executing_pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    stage: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    progress_json: Mapped[Optional[dict]] = mapped_column(JSON_TYPE, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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


# ─── Context-Aware Agentic Sandbox（Planning）──────────────────────────────────


class AssetState(Base):
    """标的资产全局态（Planning 沙盒单一真相源）。"""

    __tablename__ = "asset_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    core_logic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    radar_initial_analysis: Mapped[Optional[dict]] = mapped_column(JSON_TYPE, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planning", index=True
    )  # planning|executing|archived|discarded
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    probes: Mapped[list["ProbeTask"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class ProbeTask(Base):
    """探针开发任务（一次全局规划后批量插入）。"""

    __tablename__ = "probe_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("asset_states.id"), nullable=False, index=True
    )
    probe_blueprint: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_code", index=True
    )  # pending_code|data_ready
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    asset: Mapped["AssetState"] = relationship(back_populates="probes")
    result: Mapped[Optional["ProbeResult"]] = relationship(
        back_populates="probe_task", cascade="all, delete-orphan", uselist=False
    )


class ProbeResult(Base):
    """探针数据成果（T1 提炼后的结构化指标）。"""

    __tablename__ = "probe_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    probe_task_id: Mapped[str] = mapped_column(
        ForeignKey("probe_tasks.id"), nullable=False, unique=True, index=True
    )
    refined_data: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    probe_task: Mapped["ProbeTask"] = relationship(back_populates="result")
