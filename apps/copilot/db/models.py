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
