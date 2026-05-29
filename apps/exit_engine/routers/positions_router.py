"""持仓 SoT 同步与查询路由.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.exit_engine.data.holdings_loader import HoldingsSyncError, sync_positions_from_sot
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal

router = APIRouter(prefix="/api/positions", tags=["positions"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _position_payload(p) -> dict:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "name": p.name,
        "quantity": p.quantity,
        "cost_price": p.cost_price,
        "current_price": p.current_price,
        "market_value": p.market_value,
        "return_pct": p.return_pct,
    }


@router.post("/sync")
def sync_positions(db: Session = Depends(get_db)):
    try:
        summary = sync_positions_from_sot(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HoldingsSyncError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **summary}


@router.get("")
def list_positions(user_id: str = "default", db: Session = Depends(get_db)):
    repo = HoldingsRepository(db)
    rows = repo.list_active(user_id=user_id)
    return {
        "user_id": user_id,
        "count": len(rows),
        "positions": [_position_payload(p) for p in rows],
    }


@router.get("/{symbol}")
def get_position(symbol: str, user_id: str = "default", db: Session = Depends(get_db)):
    repo = HoldingsRepository(db)
    pos_id = f"{user_id}:{symbol}"
    row = repo.get(pos_id)
    if row is None:
        for p in repo.list_active(user_id=user_id):
            if p.symbol == symbol:
                row = p
                break
    if row is None:
        raise HTTPException(status_code=404, detail=f"持仓不存在: {symbol}")
    return _position_payload(row)
