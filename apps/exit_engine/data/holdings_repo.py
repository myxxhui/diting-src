"""持仓数据访问层.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.exit_engine.models.position import HoldingORM, Position


class HoldingsRepository:
    """从 SQLite `holdings` 表读写持仓快照。"""

    def __init__(self, session: Session):
        self.session = session

    def list_active(self, user_id: str = "default") -> list[Position]:
        stmt = select(HoldingORM).where(
            HoldingORM.user_id == user_id,
            HoldingORM.is_active.is_(True),
        )
        rows = list(self.session.scalars(stmt).all())
        return [self._to_position(row) for row in rows]

    def get(self, position_id: str) -> Optional[Position]:
        row = self.session.scalars(
            select(HoldingORM).where(HoldingORM.id == position_id)
        ).first()
        return self._to_position(row) if row else None

    def upsert(self, position: Position) -> None:
        row = self.session.scalars(
            select(HoldingORM).where(HoldingORM.id == position.id)
        ).first()
        if row is None:
            row = HoldingORM(
                id=position.id,
                user_id=position.user_id,
                symbol=position.symbol,
                name=position.name,
                quantity=position.quantity,
                cost_price=position.cost_price,
                current_price=position.current_price,
                opened_at=datetime.utcnow(),
            )
            self.session.add(row)
        else:
            row.symbol = position.symbol
            row.name = position.name
            row.quantity = position.quantity
            row.cost_price = position.cost_price
            row.current_price = position.current_price
        row.market_value = position.market_value
        row.return_pct = position.return_pct
        row.updated_at = datetime.utcnow()
        self.session.commit()

    def bulk_update_quotes(self, quotes: dict[str, float], user_id: str = "default") -> int:
        rows = list(
            self.session.scalars(
                select(HoldingORM).where(
                    HoldingORM.user_id == user_id,
                    HoldingORM.is_active.is_(True),
                )
            ).all()
        )
        updated = 0
        for row in rows:
            price = quotes.get(row.symbol)
            if price is None or price <= 0:
                continue
            row.current_price = price
            row.market_value = row.quantity * price
            if row.cost_price > 0:
                row.return_pct = price / row.cost_price - 1.0
            row.updated_at = datetime.utcnow()
            updated += 1
        self.session.commit()
        return updated

    @staticmethod
    def _to_position(row: HoldingORM) -> Position:
        return Position(
            id=row.id,
            symbol=row.symbol,
            name=row.name,
            quantity=row.quantity,
            cost_price=row.cost_price,
            current_price=row.current_price,
            user_id=row.user_id,
        )

    def deactivate(self, position_ids: Iterable[str]) -> None:
        ids = list(position_ids)
        if not ids:
            return
        self.session.execute(
            update(HoldingORM)
            .where(HoldingORM.id.in_(ids))
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        self.session.commit()
