#!/usr/bin/env python3
"""D4 step_04 · SP2 止盈预览 / 缓冲进度 / 单标的评估.

[Ref: 03_/04_维度四/.../step_04 §7.2]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from typing import Optional

from sqlalchemy import desc, select

from apps.common.holdings_sot import load_holdings_sot
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.buffer import PendingSignalORM
from apps.exit_engine.models.protocol_log import ProtocolLogORM
from apps.exit_engine.protocol_config import load_sp2_config
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.sp2_evaluator import evaluate_sp2_with_streak


def _run_preview() -> dict:
    cfg = load_sp2_config()
    proto = TakeProfitProtocol(config=cfg)
    return {
        "protocol": "SP2",
        "enabled": bool(cfg.get("enabled", True)),
        "threshold": proto.threshold,
        "priority": proto.priority,
        "buffer_days": proto.buffer_days,
        "sell_ratio": proto.sell_ratio_cfg,
    }


def _run_buffer_progress() -> dict:
    session = SessionLocal()
    try:
        stmt = (
            select(ProtocolLogORM)
            .where(ProtocolLogORM.protocol_name == "take_profit")
            .order_by(desc(ProtocolLogORM.trade_date), desc(ProtocolLogORM.id))
        )
        rows = session.scalars(stmt).all()
        latest: dict[str, ProtocolLogORM] = {}
        for row in rows:
            if row.symbol not in latest:
                latest[row.symbol] = row
        counts = Counter(r.buffer_state for r in latest.values())
        pending_detail = {
            k: v for k, v in counts.items() if k.startswith("pending_") or k == "triggered"
        }
        return {
            "symbols_with_logs": len(latest),
            "buffer_state_counts": dict(counts),
            "pending_summary": pending_detail,
            "samples": [
                {
                    "symbol": r.symbol,
                    "trade_date": r.trade_date.isoformat(),
                    "buffer_state": r.buffer_state,
                    "return_pct": r.return_pct,
                }
                for r in list(latest.values())[:8]
            ],
        }
    finally:
        session.close()


def _run_evaluate_one(symbol: str, trade_date: Optional[date] = None) -> dict:
    session = SessionLocal()
    try:
        repo = HoldingsRepository(session)
        sym = symbol.zfill(6)[-6:]
        rows = [p for p in repo.list_active() if p.symbol == sym]
        if not rows:
            return {"symbol": sym, "success": False, "error": "无 active 持仓"}
        pos = rows[0]
        proto = TakeProfitProtocol(config=load_sp2_config())
        check = proto.check(pos, {})
        result = evaluate_sp2_with_streak(pos, session=session, trade_date=trade_date)
        session.commit()
        log = session.scalars(
            select(ProtocolLogORM)
            .where(
                ProtocolLogORM.position_id == pos.id,
                ProtocolLogORM.protocol_name == "take_profit",
            )
            .order_by(desc(ProtocolLogORM.trade_date))
        ).first()
        return {
            "symbol": sym,
            "success": True,
            "position_id": pos.id,
            "hit_today": check.triggered,
            "triggered": result.triggered,
            "buffer_state": log.buffer_state if log else None,
            "return_pct": pos.return_pct,
            "audit_id": result.audit_id,
            "buffer_enqueued": result.buffer_enqueued,
        }
    finally:
        session.close()


def _run_preview_distribution() -> dict:
    """全 portfolio 三档：not_met / pending / triggered（基于当日 check + 最近 log）."""
    sot = load_holdings_sot()
    session = SessionLocal()
    try:
        repo = HoldingsRepository(session)
        active = {p.symbol: p for p in repo.list_active()}
        buckets: Counter[str] = Counter()
        rows = []
        for sym in sot.portfolio_symbols():
            pos = active.get(sym)
            if not pos:
                buckets["no_position"] += 1
                continue
            proto = TakeProfitProtocol(config=load_sp2_config())
            hit = proto.check(pos, {}).triggered
            log = session.scalars(
                select(ProtocolLogORM)
                .where(
                    ProtocolLogORM.position_id == pos.id,
                    ProtocolLogORM.protocol_name == "take_profit",
                )
                .order_by(desc(ProtocolLogORM.trade_date))
            ).first()
            if log:
                state = log.buffer_state
            elif hit:
                state = "pending_0_3"
            else:
                state = "not_met"
            if state == "triggered" or (hit and state.startswith("pending")):
                bucket = "pending" if not state == "triggered" and not hit else (
                    "triggered" if state == "triggered" else "pending"
                )
            elif hit:
                bucket = "pending"
            else:
                bucket = "not_met"
            if state == "triggered":
                bucket = "triggered"
            elif state.startswith("pending"):
                bucket = "pending"
            elif not hit:
                bucket = "not_met"
            else:
                bucket = "pending"
            buckets[bucket] += 1
            rows.append({"symbol": sym, "hit_today": hit, "buffer_state": state, "return_pct": pos.return_pct})
        return {"distribution": dict(buckets), "rows": rows}
    finally:
        session.close()


def _run_status() -> dict:
    session = SessionLocal()
    try:
        pending = session.scalars(
            select(PendingSignalORM).where(
                PendingSignalORM.protocol_name == "take_profit",
                PendingSignalORM.status == "pending",
            )
        ).all()
        logs = session.scalars(
            select(ProtocolLogORM).where(ProtocolLogORM.protocol_name == "take_profit")
        ).all()
        return {
            "sp2_config": _run_preview(),
            "pending_signals": len(pending),
            "protocol_log_rows": len(logs),
            "pending_symbols": [p.symbol for p in pending[:10]],
        }
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["preview", "buffer-progress", "evaluate-one", "preview-distribution", "status"],
    )
    parser.add_argument("--symbol", default="601138")
    parser.add_argument("--trade-date", default="", help="YYYY-MM-DD，默认今天")
    args = parser.parse_args()
    trade_date = date.fromisoformat(args.trade_date) if args.trade_date else None

    if args.mode == "preview":
        out = _run_preview()
    elif args.mode == "buffer-progress":
        out = _run_buffer_progress()
    elif args.mode == "evaluate-one":
        out = _run_evaluate_one(args.symbol, trade_date=trade_date)
    elif args.mode == "preview-distribution":
        out = _run_preview_distribution()
    else:
        out = _run_status()

    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.mode == "evaluate-one" and not out.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
