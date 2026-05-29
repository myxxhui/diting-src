#!/usr/bin/env python3
"""sell_signal payload 与 D0 AlertDispatcher 字段对齐检查。

[Ref: 03_/04_维度四/.../step_07 §7.2 exit-step07-schema]
"""
from __future__ import annotations

import sys

from apps.copilot.services.alerts.dispatcher import map_event_to_alert
from apps.exit_engine.models.sell_signal import SellSignalEvent, SignalSeverity, SignalType


REQUIRED_FIELDS = ("symbol", "signal_type", "trigger_price", "current_price", "protocol", "advice")


def main() -> int:
    event = SellSignalEvent(
        symbol="601138",
        signal_type=SignalType.STOP_LOSS,
        trigger_price=58.0,
        current_price=55.0,
        protocol="stop_loss",
        advice="测试止损建议",
        severity=SignalSeverity.EMERGENCY,
        position_id="p-601138",
    )
    stream_dict = event.to_stream_dict()
    missing = [f for f in REQUIRED_FIELDS if f not in stream_dict]
    if missing:
        print(f"❌ sell_signal 缺字段: {missing}", file=sys.stderr)
        return 1

    parsed = {k: stream_dict[k] for k in stream_dict}
    alert = map_event_to_alert("default", "events:exit:sell_signal", parsed)
    if alert is None:
        print("❌ D0 map_event_to_alert 返回 None", file=sys.stderr)
        return 1

    print("✅ sell_signal schema 与 D0 对齐 · diff=0")
    print(f"   alert_type={alert.alert_type.value} level={alert.level.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
