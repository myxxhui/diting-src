"""deep-strike ORM 模型.

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ThesisCard(Base):
    __tablename__ = "thesis_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    playbook_id: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    thesis_summary: Mapped[str] = mapped_column(String(4096), nullable=False)
    evidence_chain: Mapped[list] = mapped_column(JSON, nullable=False)
    risks: Mapped[list] = mapped_column(JSON, nullable=False)
    valuation_anchor: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    pass_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scan_log_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scan_logs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False)
    timer_signal: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_thesis_symbol_created", "symbol", "created_at"),
        Index("ix_thesis_status", "status"),
    )


class TimerSignalRecord(Base):
    """The Timer 历史归档（每次 thesis 生成快照）。"""

    __tablename__ = "timer_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_card_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timer_signal: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_by: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raw_llm_response: Mapped[Optional[str]] = mapped_column(String(65536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_timer_symbol_created", "symbol", "created_at"),)


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playbook_id: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    signals: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    pass_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_scan_symbol_created", "symbol", "created_at"),)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    scan_id: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy")
    evidence_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(String(2048), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Critic 物理门禁标记（physical 类型专用；True=通过，False=拦截，None=非物理类型）
    physical_gate: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "scan_id", "evidence_idx", name="uq_evidence_scan_idx"),
        Index("ix_evidence_symbol_scan", "symbol", "scan_id"),
        Index("ix_evidence_physical_gate", "symbol", "physical_gate"),
    )


class HumanConfirmation(Base):
    __tablename__ = "human_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    consistency_label: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("thesis_id", "reviewer", name="uq_thesis_reviewer"),)


class FinancialReport(Base):
    """三大报表入库（按报告期维度）。"""

    __tablename__ = "financial_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gross_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operating_expense: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "report_type", "period", name="uq_report"),
        Index("ix_report_symbol_period", "symbol", "period_end"),
    )


class FinancialIndicator(Base):
    __tablename__ = "financial_indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    gross_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gross_margin_qoq: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gross_margin_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    revenue_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_profit_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    receivable_turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    receivable_turnover_qoq: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    inventory_turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    inventory_turnover_qoq: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "period", name="uq_indicator"),
        Index("ix_indicator_symbol_period", "symbol", "period_end"),
    )


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    announcement_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    full_text: Mapped[Optional[str]] = mapped_column(String(65536), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="cninfo")
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "announcement_id", name="uq_announcement"),
        Index("ix_announce_symbol_pub", "symbol", "published_at"),
    )


class MapperOutput(Base):
    """The Mapper 业绩弹性闸门输出 + 标的映射。

    每条 EvidenceRecord(physical_gate=True) 对应一条 MapperOutput。
    target_symbol=null 或 status='dropped' 表示被稀释排雷（M4）或无可映射标的（M5）。

    [Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md §3.5.4]
    """

    __tablename__ = "mapper_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    elasticity_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_cap_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    reasons_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_mapper_scan_symbol", "scan_id", "symbol"),
        Index("ix_mapper_target_symbol", "target_symbol"),
        Index("ix_mapper_status_created", "status", "created_at"),
    )


class IndustryPeer(Base):
    __tablename__ = "industry_peers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    industry_code: Mapped[str] = mapped_column(String(32), nullable=False)
    industry_name: Mapped[str] = mapped_column(String(64), nullable=False)
    peer_symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    peer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    peer_metric_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("symbol", "peer_symbol", name="uq_industry_peer"),)
