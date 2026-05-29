"""exit-engine 测试共享 fixture."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from apps.exit_engine.models.position import Portfolio, Position


@pytest.fixture
def position_factory():
    def _make(
        *,
        position_id: str = "p-001",
        symbol: str = "600519",
        name: str = "贵州茅台",
        quantity: float = 100,
        cost_price: float = 1800.0,
        current_price: Optional[float] = 1500.0,
    ) -> Position:
        return Position(
            id=position_id,
            symbol=symbol,
            name=name,
            quantity=quantity,
            cost_price=cost_price,
            current_price=current_price,
        )

    return _make


@pytest.fixture
def portfolio_factory(position_factory):
    def _make(positions: Optional[list[Position]] = None, total_value: float = 1_000_000.0) -> Portfolio:
        return Portfolio(
            user_id="default",
            positions=positions or [position_factory()],
            total_value=total_value,
        )

    return _make


@pytest.fixture
def now_utc() -> datetime:
    return datetime.now(timezone.utc)
