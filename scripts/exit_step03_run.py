#!/usr/bin/env python3
"""D4 step_03 · SP1 预览 / 单标的评估 / 边界自检.

[Ref: 03_/04_维度四/.../step_03 §7.2]
"""
from __future__ import annotations

import argparse
import json
import sys

from apps.common.holdings_sot import load_holdings_sot
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.protocol_config import load_sp1_config
from apps.exit_engine.protocols.stop_loss import StopLossProtocol
from apps.exit_engine.services.protocol_runner import evaluate_and_audit


def _run_preview() -> dict:
    cfg = load_sp1_config()
    return {
        "protocol": "SP1",
        "enabled": bool(cfg.get("enabled", True)),
        "threshold": cfg.get("threshold", -0.15),
        "priority": cfg.get("priority", 1),
        "buffer_days": cfg.get("buffer_days", 0),
        "sell_ratio": cfg.get("sell_ratio", 1.0),
        "skip_closed_market": cfg.get("skip_closed_market", True),
    }


def _run_evaluate_one(symbol: str) -> dict:
    session = SessionLocal()
    try:
        repo = HoldingsRepository(session)
        rows = [p for p in repo.list_active() if p.symbol == symbol.zfill(6)[-6:]]
        if not rows:
            return {"symbol": symbol, "success": False, "error": "无 active 持仓"}
        pos = rows[0]
        proto = StopLossProtocol(config=load_sp1_config())
        result = evaluate_and_audit(proto, pos, session=session)
        return {
            "symbol": pos.symbol,
            "success": True,
            "position_id": pos.id,
            "triggered": result.triggered,
            "audit_id": result.audit_id,
            "return_pct": pos.return_pct,
        }
    finally:
        session.close()


def _run_threshold_test() -> dict:
    """L3 边界：-14% 不触发；-15% 触发；缺 cost 跳过."""
    from apps.exit_engine.models.position import Position

    proto = StopLossProtocol(config=load_sp1_config())
    cases = [
        (100.0, 86.0, False),
        (100.0, 85.0, True),
        (100.0, 85.01, False),
        (100.0, 50.0, True),
    ]
    rows = []
    for cost, current, expect in cases:
        pos = Position(
            id="test",
            symbol="TEST",
            name="TEST",
            quantity=100,
            cost_price=cost,
            current_price=current,
        )
        chk = proto.check(pos, {})
        rows.append(
            {
                "cost": cost,
                "current": current,
                "expect_triggered": expect,
                "actual_triggered": chk.triggered,
                "ok": chk.triggered == expect,
            }
        )
    pos_skip = Position(
        id="test2",
        symbol="TEST",
        name="TEST",
        quantity=100,
        cost_price=0,
        current_price=85.0,
    )
    skip = proto.check(pos_skip, {})
    rows.append({"case": "missing_cost", "triggered": skip.triggered, "ok": not skip.triggered})
    ok = all(r.get("ok") for r in rows)
    return {"threshold_tests": rows, "ok": ok}


def _run_status() -> dict:
    sot = load_holdings_sot()
    cfg = load_sp1_config()
    session = SessionLocal()
    try:
        n = len(HoldingsRepository(session).list_active())
    finally:
        session.close()
    return {
        "portfolio_symbols": sot.portfolio_symbols(),
        "active_count": len(sot.active_symbols()),
        "db_active": n,
        "sp1_threshold": cfg.get("threshold"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["preview", "evaluate-one", "threshold-test", "status"],
    )
    parser.add_argument("--symbol", default="601138")
    args = parser.parse_args()
    if args.mode == "preview":
        out = _run_preview()
    elif args.mode == "evaluate-one":
        out = _run_evaluate_one(args.symbol)
    elif args.mode == "threshold-test":
        out = _run_threshold_test()
    else:
        out = _run_status()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.mode == "threshold-test" and not out.get("ok"):
        raise SystemExit(1)
    if args.mode == "evaluate-one" and not out.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
