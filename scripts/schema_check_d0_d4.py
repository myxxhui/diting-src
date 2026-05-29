#!/usr/bin/env python3
"""HealthChangeEvent → D0 handle_health_change / D4 SP3 字段对齐（diff=0）。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 G]
"""
from __future__ import annotations

import inspect
import sys

from apps.copilot.events.handlers import health_change as d0_handler
from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol
from apps.exit_engine.models.position import Position
from apps.state_watch.events.health_change import HealthChangeEvent

D0_REQUIRED = {
    "event_id",
    "symbol",
    "name",
    "old_health",
    "new_health",
    "health_delta",
    "push_level",
    "change_reason",
    "node_state",
    "timestamp",
}

D4_REQUIRED = {
    "symbol",
    "new_state",
    "narrative_label",
    "narrative_invalid_count",
    "event_id",
}


def main() -> int:
    ev = HealthChangeEvent(
        symbol="601138",
        name="工业富联",
        old_state="growing",
        new_state="exit",
        old_health=85.0,
        new_health=20.0,
        narrative_label="contradiction",
        narrative_invalid_count=3,
        rule_id="T6",
        reason="健康度 20.0 < 30",
    )
    payload = ev.to_stream_payload()

    missing_d0 = D0_REQUIRED - set(payload.keys())
    missing_d4 = D4_REQUIRED - set(payload.keys())
    if missing_d0:
        print(f"❌ D0 缺字段: {missing_d0}", file=sys.stderr)
        return 1
    if missing_d4:
        print(f"❌ D4 缺字段: {missing_d4}", file=sys.stderr)
        return 1

    pos = Position(
        id="schema",
        symbol="601138",
        name="工业富联",
        quantity=100,
        cost_price=10.0,
        current_price=10.0,
    )
    proto = ThesisInvalidProtocol()
    ctx = {
        "new_state": payload["new_state"],
        "narrative_label": payload["narrative_label"],
        "narrative_invalid_count": payload["narrative_invalid_count"],
        "health_change_event_id": payload["event_id"],
    }
    if not proto.check(pos, ctx).triggered:
        print("❌ D4 SP3 未触发（schema 不兼容）", file=sys.stderr)
        return 1

    sig = inspect.signature(d0_handler.handle_health_change)
    if "payload" not in sig.parameters:
        print("❌ D0 handler 签名异常", file=sys.stderr)
        return 1

    print("✅ schema_check_d0_d4: D0+D4 字段齐全 · SP3 可触发 · field_diff=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
