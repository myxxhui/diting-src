"""M4 价值账本 ORM 模型。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
[DNA: _System_DNA/00_co_pilot/dna_stage_1_启动期.yaml#deliverables.modules[3]]
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.copilot.db.database import Base


class Octant(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"


class ResponseKind(str, enum.Enum):
    RECOMMENDATION = "recommendation"
    ALERT = "alert"


class UserResponse(Base):
    """用户对系统建议（推荐 / 告警）的响应记录。"""

    __tablename__ = "user_responses"
    __table_args__ = (
        UniqueConstraint("user_id", "ref_id", "kind", name="uq_response_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    system_advice: Mapped[str] = mapped_column(String(32), nullable=False)
    user_action: Mapped[str] = mapped_column(String(32), nullable=False)
    advice_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AttributionRecord(Base):
    """8 象限归因记录。"""

    __tablename__ = "attributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    response_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    octant: Mapped[str] = mapped_column(String(1), nullable=False, index=True)
    system_advice: Mapped[str] = mapped_column(String(32), nullable=False)
    user_action: Mapped[str] = mapped_column(String(32), nullable=False)
    result_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    scs_delta: Mapped[float] = mapped_column(Float, default=0.0)
    ev_delta: Mapped[float] = mapped_column(Float, default=0.0)
    attribution_text: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class MonthlyReport(Base):
    """月报落库记录。"""

    __tablename__ = "monthly_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_report_user_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    scs: Mapped[float] = mapped_column(Float, default=0.0)
    ev: Mapped[float] = mapped_column(Float, default=0.0)
    octant_distribution: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CircuitBreakerState(Base):
    """自我熔断状态：当前是否暂停推送 + 上次切换时间。"""

    __tablename__ = "circuit_breaker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paused: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str] = mapped_column(String(512), default="")
    last_window_size: Mapped[int] = mapped_column(Integer, default=0)
    last_bh_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
