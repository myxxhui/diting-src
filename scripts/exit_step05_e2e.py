#!/usr/bin/env python3
"""D4 step_05 Redis 真流 e2e：xadd → XREADGROUP → process → xack。

[Ref: 03_/04_维度四/.../step_05 §7.2 exit-step05-e2e-real / sp5-e2e-real]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from apps.exit_engine.db.init_db import init
from apps.exit_engine.events.redis_runner import ExitStreamRedisRunner
from apps.exit_engine.services.stream_consumer import (
    HEALTH_CHANGE_STREAM,
    HEALTH_CONSUMER_GROUP,
    SP5_CONSUMER_GROUP,
    TIMER_SIGNAL_STREAM,
)


def _redis_url() -> str:
    return (
        os.environ.get("EXIT_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/2"
    )


def _ensure_holding(db, symbol: str) -> None:
    from apps.exit_engine.models.position import HoldingORM

    pos_id = f"e2e-{symbol}"
    if db.query(HoldingORM).filter_by(id=pos_id).one_or_none():
        return
    db.add(
        HoldingORM(
            id=pos_id,
            user_id="default",
            symbol=symbol,
            name=symbol,
            quantity=100,
            cost_price=50.0,
            current_price=55.0,
            is_active=True,
        )
    )
    db.commit()


def run_sp3(runner: ExitStreamRedisRunner) -> int:
    from apps.exit_engine.db.session import SessionLocal

    init()
    db = SessionLocal()
    try:
        _ensure_holding(db, "002837")
    finally:
        db.close()

    event_id = f"hc-e2e-{uuid.uuid4().hex[:10]}"
    payload = {
        "symbol": "002837",
        "new_state": "exit",
        "event_id": event_id,
    }
    msg_id, result = runner.publish_and_consume(
        HEALTH_CHANGE_STREAM,
        HEALTH_CONSUMER_GROUP,
        payload,
        consumer_name="exit_e2e_sp3",
    )
    print(f"SP3 xadd msg_id={msg_id} handled={result.handled if result else None} "
          f"triggered={result.triggered if result else None}")
    if result and result.event:
        print(f"  advice={result.event.advice[:80]}")
    return 0 if result and result.triggered else 1


def run_sp5(runner: ExitStreamRedisRunner) -> int:
    from apps.exit_engine.db.session import SessionLocal

    init()
    db = SessionLocal()
    try:
        _ensure_holding(db, "300308")
    finally:
        db.close()

    event_id = f"ts-e2e-{uuid.uuid4().hex[:10]}"
    stages_ok = 0
    for stage in ("left_accumulate", "main_wave", "retreat"):
        payload = {
            "symbol": "300308",
            "stage": stage,
            "event_id": f"{event_id}-{stage}",
            "evidence_url": "https://example.com/e2e-redis",
            "financial_report_date": "2026-08-15",
        }
        msg_id, result = runner.publish_and_consume(
            TIMER_SIGNAL_STREAM,
            SP5_CONSUMER_GROUP,
            payload,
            consumer_name="exit_e2e_sp5",
        )
        ok = result is not None and result.triggered
        stages_ok += int(ok)
        print(f"SP5 stage={stage} msg_id={msg_id} triggered={ok}")
    print(f"SP5 三段统计: {stages_ok}/3")
    return 0 if stages_ok == 3 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", choices=["SP3", "SP5", "ALL"], default="ALL")
    args = parser.parse_args()

    url = _redis_url()
    runner = ExitStreamRedisRunner(url)
    try:
        runner.ping()
    except Exception as exc:
        print(f"❌ Redis 不可用 {url}: {exc}", file=sys.stderr)
        return 1
    print(f"✅ Redis ping OK · {url}")
    runner.ensure_all_groups()

    if args.protocol == "SP3":
        return run_sp3(runner)
    if args.protocol == "SP5":
        return run_sp5(runner)
    rc = run_sp3(runner)
    rc = max(rc, run_sp5(runner))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
