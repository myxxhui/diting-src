"""利润截留扫描仪 CLI。[Ref: step_04]"""
from __future__ import annotations

import asyncio
import json
import sys

from apps.deep_strike.data.ingest import run as ingest_run
from apps.deep_strike.db.database import init_db
from apps.deep_strike.playbooks.profit_capture.playbook import ProfitCapturePlaybook


async def _run(symbols: list[str]) -> None:
    await init_db()
    pb = ProfitCapturePlaybook()
    for s in symbols:
        r = await pb.scan(s)
        summary = {
            "symbol": r.symbol,
            "decision": r.decision,
            "confidence": r.confidence,
            "signals_hit": [sig.id for sig in r.signals if sig.hit],
            "evidence_count": len(r.evidence),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    symbols = sys.argv[1:] or ["600519"]
    asyncio.run(_run(symbols))


if __name__ == "__main__":
    main()
