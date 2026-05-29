#!/usr/bin/env python3
"""100 笔历史回测：协议触发 + 冲突准确率 ≥0.95。

[Ref: 03_/04_维度四/.../step_07 §7.2 exit-step07-backtest]
TEST_ONLY fixture: tests/exit_engine/fixtures/backtest_history.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from apps.exit_engine.models.position import Portfolio, Position
from apps.exit_engine.services.exit_engine_orchestrator import evaluate_protocols_dry

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "exit_engine" / "fixtures" / "backtest_history.csv"


def _generate_fixture(path: Path) -> None:
    """生成 100 行 TEST_ONLY 回测样本（4 协议各≥20 + 冲突≥10）。"""
    rows: list[dict[str, str]] = []
    idx = 0

    def add(symbol: str, cost: float, current: float, expected: str, ctx: dict | None = None) -> None:
        nonlocal idx
        idx += 1
        rows.append(
            {
                "row_id": str(idx),
                "symbol": symbol,
                "cost_price": f"{cost:.4f}",
                "current_price": f"{current:.4f}",
                "context_json": json.dumps(ctx or {}, ensure_ascii=False),
                "expected_signal": expected,
            }
        )

    for i in range(22):
        add(f"SL{i:03d}", 100.0, 80.0, "stop_loss")
    for i in range(22):
        add(f"TP{i:03d}", 100.0, 135.0, "take_profit")
    for i in range(20):
        add(f"TI{i:03d}", 50.0, 52.0, "thesis_invalid", {"new_state": "exit"})
    for i in range(20):
        add(f"RB{i:03d}", 10.0, 10.0, "rebalance", {"mv": 300_000, "total": 1_000_000})
    for i in range(6):
        add(f"SP5{i:03d}", 20.0, 22.0, "financial_window", {"stage": "retreat"})

    # 冲突场景 ≥10：期望 winner
    for i in range(5):
        add(f"C1{i:03d}", 100.0, 80.0, "stop_loss", {"new_state": "exit"})
    for i in range(3):
        add(f"C2{i:03d}", 100.0, 135.0, "take_profit", {"mv": 300_000, "total": 1_000_000})
    for i in range(2):
        add(f"C3{i:03d}", 100.0, 80.0, "stop_loss", {"new_state": "exit", "mv": 300_000, "total": 1_000_000})

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["row_id", "symbol", "cost_price", "current_price", "context_json", "expected_signal"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _run_backtest(csv_path: Path) -> tuple[float, dict[str, int], list[str]]:
    correct = 0
    total = 0
    confusion: Counter[str] = Counter()
    errors: list[str] = []

    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            pos = Position(
                id=f"bt-{row['row_id']}",
                symbol=row["symbol"],
                name=row["symbol"],
                quantity=100,
                cost_price=float(row["cost_price"]),
                current_price=float(row["current_price"]),
            )
            portfolio = Portfolio(user_id="backtest", positions=[pos], total_value=1_000_000.0)
            ctx = json.loads(row.get("context_json") or "{}")
            resolution = evaluate_protocols_dry(pos, portfolio, context=ctx)
            expected = row["expected_signal"]
            actual = resolution.winner.signal_type.value if resolution.winner else "none"
            key = f"{expected}->{actual}"
            confusion[key] += 1
            if actual == expected:
                correct += 1
            else:
                errors.append(f"row {row['row_id']} {row['symbol']}: expected={expected} actual={actual}")

    accuracy = correct / total if total else 0.0
    return accuracy, dict(confusion), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(FIXTURE))
    parser.add_argument("--min-accuracy", type=float, default=0.95)
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if args.regenerate or not csv_path.exists():
        print(f"▶ 生成 TEST_ONLY fixture → {csv_path}")
        _generate_fixture(csv_path)

    accuracy, confusion, errors = _run_backtest(csv_path)
    print(f"回测样本: {csv_path.name} 行数={sum(confusion.values())}")
    print(f"准确率: {accuracy:.2%} (门槛 ≥{args.min_accuracy:.0%})")
    print("混淆矩阵 (expected->actual):")
    for k, v in sorted(confusion.items()):
        print(f"  {k}: {v}")

    if errors:
        print("\n前 10 条偏差:")
        for line in errors[:10]:
            print(f"  ❌ {line}")

    if accuracy < args.min_accuracy:
        print(f"\n❌ 准确率 {accuracy:.2%} < {args.min_accuracy:.0%}", file=sys.stderr)
        return 1
    print("\n✅ 回测准出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
