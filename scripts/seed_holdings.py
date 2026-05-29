"""注入 10 笔模拟持仓,用于后续协议(SP1~SP4)测试.

[Ref: 03_/04_维度四/.../step_02]

使用: python scripts/seed_holdings.py
"""
from __future__ import annotations

import sys
from datetime import datetime

from sqlalchemy import select

from apps.exit_engine.db.init_db import init as init_db
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.position import HoldingORM

SEED_HOLDINGS = [
    {"id": "p-001", "symbol": "600519", "name": "贵州茅台", "quantity": 100, "cost_price": 1800.0},
    {"id": "p-002", "symbol": "000858", "name": "五粮液", "quantity": 1000, "cost_price": 220.0},
    {"id": "p-003", "symbol": "601318", "name": "中国平安", "quantity": 5000, "cost_price": 34.0},
    {"id": "p-004", "symbol": "000333", "name": "美的集团", "quantity": 2000, "cost_price": 55.0},
    {"id": "p-005", "symbol": "002594", "name": "比亚迪", "quantity": 1500, "cost_price": 180.0},
    {"id": "p-006", "symbol": "300750", "name": "宁德时代", "quantity": 1500, "cost_price": 180.0},
    {"id": "p-007", "symbol": "600036", "name": "招商银行", "quantity": 1000, "cost_price": 38.0},
    {"id": "p-008", "symbol": "000651", "name": "格力电器", "quantity": 1000, "cost_price": 38.0},
    {"id": "p-009", "symbol": "000001", "name": "平安银行", "quantity": 1000, "cost_price": 12.0},
    {"id": "p-010", "symbol": "601888", "name": "中国中免", "quantity": 500, "cost_price": 100.0},
]


def main() -> int:
    init_db()
    session = SessionLocal()
    inserted = 0
    try:
        for h in SEED_HOLDINGS:
            row = session.scalars(select(HoldingORM).where(HoldingORM.id == h["id"])).first()
            if row:
                continue
            session.add(
                HoldingORM(
                    id=h["id"],
                    user_id="default",
                    symbol=h["symbol"],
                    name=h["name"],
                    quantity=h["quantity"],
                    cost_price=h["cost_price"],
                    opened_at=datetime.utcnow(),
                    is_active=True,
                )
            )
            inserted += 1
        session.commit()
    finally:
        session.close()
    print(f"✅ 模拟持仓注入完成: 新增 {inserted} 笔(已存在则跳过)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
