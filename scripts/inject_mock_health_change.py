"""向 Redis 注入 mock health_change — 已禁用（no-mock-policy）.

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
"""
import sys

if __name__ == "__main__":
    print(
        "❌ inject_mock_health_change 已禁用（no-mock-policy）。"
        " 请等待 D3 health_change 真流。",
        file=sys.stderr,
    )
    raise SystemExit(2)
