"""SP2 等协议按交易日评估日志（连续缓冲计数）.

[Ref: 03_/04_维度四/.../step_04_SP2止盈协议.md §3]
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.exit_engine.models.position import Base


class ProtocolLogORM(Base):
    __tablename__ = "protocol_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    protocol_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    buffer_state: Mapped[str] = mapped_column(String(32), nullable=False, default="not_met")
    return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("position_id", "protocol_name", "trade_date", name="uq_protocol_log_day"),
        Index("idx_protocol_log_symbol_proto", "symbol", "protocol_name", "trade_date"),
    )
