"""step_17 安全扫描门控 demo：模拟 fraud → 加仓建议被压制。

[Ref: step_17_执行中仓位指导.md §3.2]
"""
from __future__ import annotations
import asyncio
import sys
sys.path.insert(0, ".")

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol
from apps.copilot.modules.execution.advisor import _build_advice
from apps.common.holdings_sot import HoldingEntry
from sqlalchemy import select


async def main():
    await init_db()

    print("▶ 安全扫描 fraud 场景模拟：")

    # 模拟已持仓标的 + 证伪全部 ok + 但 fraud
    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=8.0)
    tasks = [{"falsify_type": t, "verdict": "ok"} for t in ("moat", "catalyst", "niche", "risk")]
    readiness = {"total": 4, "ok_rate": 1.0, "falsified": 0, "pending": 0, "ready_for_executing": True}

    action, rationale, evidence = _build_advice(
        h, 10.0, False, tasks, readiness, "concept", True, "fraud"
    )
    print(f"  fraud 场景 → advice_action = {action}")
    print(f"  rationale = {rationale}")
    assert "清仓" in action or "风险" in action, "❌ fraud 未压制加仓建议"
    print("  ✅ fraud → 加仓建议被压制（标红 advisory）")

    # 模拟 safety=pending → 暂缓加仓
    action2, rationale2, _ = _build_advice(
        h, 10.0, False, tasks, readiness, "concept", True, "pending"
    )
    print(f"\n  pending 场景 → advice_action = {action2}")
    assert "清仓" not in action2, "❌ pending 不应触发清仓"
    print("  ✅ pending → 不清仓，标注暂缓")

    # 正常 ok 场景
    action3, rationale3, _ = _build_advice(
        h, 10.0, False, tasks, readiness, "concept", True, "ok"
    )
    print(f"\n  ok 场景 → advice_action = {action3}")
    print("  ✅ ok → 正常建议生成")

    print("\n✅ 盘后安全扫描门控 demo 完成")


if __name__ == "__main__":
    asyncio.run(main())
