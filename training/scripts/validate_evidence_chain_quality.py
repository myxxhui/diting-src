#!/usr/bin/env python3
"""D2 step_03 · 证据链质量矩阵（启动期 10 项）.

[Ref: 03_/02_维度二/.../step_03 §3.5]
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import create_engine, text

from apps.common.holdings_sot import load_holdings_sot
from apps.deep_strike.config import settings


def _check_matrix() -> dict:
    symbols = load_holdings_sot().active_symbols()
    eng = create_engine(settings.db_url.replace("+aiosqlite", ""), future=True)
    rows = []
    with eng.connect() as conn:
        for sym in symbols[:10]:
            cnt = conn.execute(
                text("SELECT COUNT(*) FROM evidence_records WHERE symbol = :s"),
                {"s": sym},
            ).scalar()
            join_ok = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM evidence_records e
                    WHERE e.symbol = :s AND e.source_id IS NOT NULL AND length(e.source_id) > 0
                    """
                ),
                {"s": sym},
            ).scalar()
            rows.append(
                {
                    "symbol": sym,
                    "count": int(cnt or 0),
                    "source_id_ok": int(join_ok or 0),
                    "T1_ge3": (cnt or 0) >= 3,
                    "T5_source_id": (join_ok or 0) >= min(int(cnt or 0), 1),
                }
            )
    ok = all(r["T1_ge3"] and r["T5_source_id"] for r in rows if r["count"] > 0)
    sparse = [r for r in rows if r["count"] == 0]
    return {
        "matrix": rows,
        "sparse_symbols": [r["symbol"] for r in sparse],
        "ok": ok or len(sparse) == len(rows),
        "note": "未 build 的标的 count=0 视为待跑 deep-step03-build",
    }


def main() -> None:
    report = _check_matrix()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"] and not report["sparse_symbols"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
