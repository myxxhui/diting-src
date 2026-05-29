"""向 copilot 注入 mock health_change — 已禁用（no-mock-policy）.

请等待 D3 step_07 真 health_change 事件流，或使用 tests/ 内 fixture。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
"""
import sys

if __name__ == "__main__":
    print(
        "❌ copilot_inject_health 已禁用（no-mock-policy）。"
        " 请等待 D3 health_change 真流；单测见 tests/copilot/test_health_consumer.py",
        file=sys.stderr,
    )
    raise SystemExit(2)
