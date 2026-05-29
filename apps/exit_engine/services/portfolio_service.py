"""组合汇总服务.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.models.position import Portfolio, Position


class PortfolioService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = HoldingsRepository(session)

    def get_portfolio(self, user_id: str = "default") -> Portfolio:
        positions: list[Position] = self.repo.list_active(user_id=user_id)
        total_value = 0.0
        for p in positions:
            mv = p.market_value
            if mv is not None:
                total_value += mv
        return Portfolio(user_id=user_id, positions=positions, total_value=total_value)
