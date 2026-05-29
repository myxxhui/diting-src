"""持仓领域模型与 ORM 映射.

[Ref: 03_/04_维度四/.../step_01]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class HoldingORM(Base):
    __tablename__ = "holdings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True, default="default")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


@dataclass
class Position:
    id: str
    symbol: str
    name: str
    quantity: float
    cost_price: float
    current_price: Optional[float] = None
    user_id: str = "default"

    @property
    def market_value(self) -> Optional[float]:
        if self.current_price is None:
            return None
        return self.quantity * self.current_price

    @property
    def return_pct(self) -> Optional[float]:
        if self.current_price is None or self.cost_price <= 0:
            return None
        return self.current_price / self.cost_price - 1.0


@dataclass
class Portfolio:
    user_id: str
    positions: list[Position]
    total_value: float

    def ratio_of(self, position: Position) -> Optional[float]:
        if self.total_value <= 0 or position.market_value is None:
            return None
        return position.market_value / self.total_value
