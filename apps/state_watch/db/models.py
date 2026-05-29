"""SQLAlchemy 三表模型.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class HoldingState(Base):
    __tablename__ = "holdings_state"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    thesis_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thesis_summary: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="growing")
    health_score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    push_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slis: Mapped[list] = mapped_column(JSON, nullable=False, insert_default=list)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, insert_default=dict)
    state_entered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    health_records = relationship("HealthRecord", back_populates="holding", cascade="all,delete-orphan")
    transitions = relationship(
        "StateTransition", back_populates="holding", cascade="all,delete-orphan"
    )
    sli_values = relationship(
        "NodeSLIValue", back_populates="holding", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_holdings_state_symbol_state", "symbol", "state"),)


class HealthRecord(Base):
    __tablename__ = "health_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    holding_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("holdings_state.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    sli_score: Mapped[float] = mapped_column(Float, nullable=False)
    narrative_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    sli_details: Mapped[dict] = mapped_column(JSON, nullable=False, insert_default=dict)
    narrative_label: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    push_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    holding = relationship("HoldingState", back_populates="health_records")


class StateTransition(Base):
    __tablename__ = "state_transitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    holding_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("holdings_state.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str] = mapped_column(String(16), nullable=False)
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    from_health: Mapped[float] = mapped_column(Float, nullable=False)
    to_health: Mapped[float] = mapped_column(Float, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(8), nullable=False, default="NONE")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sli_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, insert_default=dict)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    holding = relationship("HoldingState", back_populates="transitions")


class NodeSLIValue(Base):
    """节点级 SLI 值快照(每个 holding × 每个 metric 一行).

    [Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
    """

    __tablename__ = "node_sli_values"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    holding_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("holdings_state.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sli_id: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    probe_type: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    operator: Mapped[str] = mapped_column(String(8), nullable=False, default=">")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    current_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_score: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    holding = relationship("HoldingState", back_populates="sli_values")

    __table_args__ = (
        Index("idx_node_sli_holding_metric", "holding_id", "metric", unique=True),
    )


class FailedStreamPublish(Base):
    """Redis Stream XADD 失败兜底（step_07 retry_worker 重试）。

    [Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 C]
    """

    __tablename__ = "failed_stream_publish"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    retried_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class MarketPhaseRecord(Base):
    """市场阶段分类历史（INSERT-only · 按 symbol+classified_at 查询最新）.

    [Ref: 03_/03_维度三/.../step_09_市场阶段分类器MVP.md §3]
    """

    __tablename__ = "market_phase_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    market_phase: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning_tags: Mapped[list] = mapped_column(JSON, nullable=False, insert_default=list)
    rule_signals: Mapped[dict] = mapped_column(JSON, nullable=False, insert_default=dict)
    classifier_version: Mapped[str] = mapped_column(String(20), nullable=False, default="rule_v1")

    __table_args__ = (Index("idx_market_phase_symbol_time", "symbol", "classified_at"),)
