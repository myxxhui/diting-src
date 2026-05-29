"""组合查询路由.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{user_id}")
def get_portfolio(user_id: str, db: Session = Depends(get_db)):
    portfolio = PortfolioService(db).get_portfolio(user_id=user_id)
    return {
        "user_id": portfolio.user_id,
        "total_value": portfolio.total_value,
        "positions": [
            {
                "id": p.id,
                "symbol": p.symbol,
                "name": p.name,
                "quantity": p.quantity,
                "cost_price": p.cost_price,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "return_pct": p.return_pct,
                "ratio": portfolio.ratio_of(p),
            }
            for p in portfolio.positions
        ],
    }
