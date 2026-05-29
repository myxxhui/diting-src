#!/usr/bin/env python3
"""D2 step_03 · 全 active 标的构建证据链.

[Ref: 03_/02_维度二/.../step_03 §7.2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import func, select

from apps.common.holdings_sot import load_holdings_sot
from apps.deep_strike.db.database import AsyncSessionLocal, init_db
from apps.deep_strike.db.models import EvidenceRecord
from apps.deep_strike.engines.critic_bridge import (
    critic_enabled,
    default_critic,
    prepare_critic_inputs,
)
from apps.deep_strike.engines.evidence_builder import EvidenceChainBuilder
from apps.deep_strike.engines.evidence_models import EvidenceType


async def _build_all(symbols: list[str], scan_id: str | None, sot) -> dict:
    await init_db()
    sid = scan_id or datetime.now(timezone.utc).strftime("%Y%m%d")
    rows = []
    critic = default_critic() if critic_enabled() else None
    async with AsyncSessionLocal() as session:
        for sym in symbols:
            try:
                entry = sot.by_symbol(sym)
                segment = entry.segment if entry else None
                critic_inputs = (
                    await prepare_critic_inputs(session, sym, segment=segment)
                    if critic is not None
                    else []
                )
                chain = await EvidenceChainBuilder(session).build(
                    sym,
                    scan_id=sid,
                    critic_inputs=critic_inputs or None,
                    critic=critic if critic_inputs else None,
                )
                physical_n = sum(1 for e in chain.items if e.type == EvidenceType.PHYSICAL)
                cnt = await session.scalar(
                    select(func.count(EvidenceRecord.id)).where(
                        EvidenceRecord.symbol == sym,
                        EvidenceRecord.scan_id == sid,
                    )
                )
                rows.append(
                    {
                        "symbol": sym,
                        "success": True,
                        "scan_id": sid,
                        "evidence_count": len(chain.items),
                        "physical_evidence_count": physical_n,
                        "critic_clusters": len(critic_inputs),
                        "db_rows": int(cnt or 0),
                    }
                )
            except Exception as exc:
                rows.append({"symbol": sym, "success": False, "error": str(exc)})
    ok = sum(1 for r in rows if r.get("success"))
    return {"scan_id": sid, "total": len(rows), "ok": ok, "rows": rows}


async def _status() -> dict:
    await init_db()
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count(EvidenceRecord.id)))
    sot = load_holdings_sot()
    return {"evidence_records_total": int(total or 0), "active": sot.active_symbols()}


async def _main(mode: str, scan_id: str | None) -> int:
    if mode == "status":
        print(json.dumps(await _status(), ensure_ascii=False, indent=2))
        return 0
    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    if not symbols:
        print("❌ SoT 无 active 标的", file=sys.stderr)
        return 1
    report = await _build_all(symbols, scan_id, sot)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] == report["total"] else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["build", "status"])
    parser.add_argument("--scan-id", default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.mode, args.scan_id)))


if __name__ == "__main__":
    main()
