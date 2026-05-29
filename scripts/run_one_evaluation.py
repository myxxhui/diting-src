#!/usr/bin/env python3
"""D4 step_07 单笔评估 + 可选真 XADD。

[Ref: 03_/04_维度四/.../step_07 §7.2 exit-step07-publish-once]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.init_db import init
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.services.exit_engine_orchestrator import ExitEngineOrchestrator
from apps.exit_engine.services.portfolio_service import PortfolioService


def _ensure_demo_stop_loss(db, user_id: str) -> str:
    from apps.exit_engine.models.position import HoldingORM

    pos_id = "step07-demo-sl"
    row = db.query(HoldingORM).filter_by(id=pos_id).one_or_none()
    if row is None:
        db.add(
            HoldingORM(
                id=pos_id,
                user_id=user_id,
                symbol="STEP07",
                name="step07演示",
                quantity=100,
                cost_price=100.0,
                current_price=80.0,
                return_pct=-0.20,
                is_active=True,
            )
        )
    else:
        row.current_price = 80.0
        row.return_pct = -0.20
        row.is_active = True
    db.commit()
    return pos_id


def main() -> int:
    parser = argparse.ArgumentParser(description="exit-engine 单笔/全组合评估")
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--position-id", default=None, help="不指定则评估全部 active 持仓")
    parser.add_argument("--publish", action="store_true", help="真 XADD sell_signal")
    parser.add_argument("--demo-stop-loss", action="store_true", help="写入演示持仓并触发 SP1")
    parser.add_argument("--context-json", default="{}", help="SP3/SP5 等上下文 JSON")
    args = parser.parse_args()

    init()
    db = SessionLocal()
    try:
        ctx = json.loads(args.context_json)
        if args.demo_stop_loss:
            args.position_id = _ensure_demo_stop_loss(db, args.user_id)
            args.publish = True
        orch = ExitEngineOrchestrator(db, publish=args.publish)
        portfolio = PortfolioService(db).get_portfolio(user_id=args.user_id)
        if args.position_id:
            repo = HoldingsRepository(db)
            pos = repo.get(args.position_id)
            if pos is None:
                print(f"❌ position {args.position_id} 不存在", file=sys.stderr)
                return 1
            result = orch.evaluate_position(pos, portfolio, context=ctx, user_id=args.user_id)
            results = [result]
        else:
            results = orch.evaluate_portfolio(portfolio, user_id=args.user_id)

        for r in results:
            print(
                f"  {r.symbol}: triggered={r.triggered_protocols} "
                f"winner={r.winner.signal_type.value if r.winner else None} "
                f"published={r.published} msg={r.stream_msg_id}"
            )

        if args.publish:
            import redis

            url = os.environ.get("EXIT_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/2"
            client = redis.from_url(url, decode_responses=True)
            length = client.xlen("events:exit:sell_signal")
            print(f"✅ events:exit:sell_signal XLEN={length}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
