#!/usr/bin/env python3
"""SP5 / SP3 Stream payload schema 解码验证。

[Ref: 03_/04_维度四/.../step_05 §7.2 exit-step05-schema]
"""
from __future__ import annotations

import json
import sys

SAMPLES = {
    "health_change": {
        "symbol": "002837",
        "new_state": "exit",
        "narrative_label": "contradiction",
        "narrative_invalid_count": 3,
        "event_id": "hc-schema-check",
    },
    "timer_signal": {
        "symbol": "300308",
        "stage": "main_wave",
        "evidence_url": "https://example.com/report",
        "financial_report_date": "2026-08-15",
        "execute_mode": "advisory",
    },
}


def main() -> int:
    from apps.exit_engine.protocols.sp5_financial_window import normalize_stage
    from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol
    from apps.exit_engine.models.position import Position

    pos = Position(
        id="schema-check",
        symbol="002837",
        name="test",
        quantity=100,
        cost_price=10.0,
        current_price=10.0,
    )

    hc = SAMPLES["health_change"]
    proto3 = ThesisInvalidProtocol()
    r3 = proto3.check(pos, hc)
    if not r3.triggered:
        print("❌ health_change schema 解码后 SP3 未触发", file=sys.stderr)
        return 1

    ts = SAMPLES["timer_signal"]
    stage = normalize_stage(ts["stage"])
    if stage != "main_wave":
        print("❌ timer_signal stage 解码失败", file=sys.stderr)
        return 1

    print("✅ health_change / timer_signal payload schema 解码 OK")
    print(json.dumps({"health_change": hc, "timer_signal": ts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
