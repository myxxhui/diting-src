"""10 持仓 fixture — 覆盖 T1~T6 与无转移场景。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 E]
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.state_watch.health.orchestrator import PositionSnapshot


@dataclass
class PositionFixtureCase:
    symbol: str
    name: str
    snapshot: PositionSnapshot
    expected_state: str
    expected_rule: str | None


POSITIONS_10: list[PositionFixtureCase] = [
    PositionFixtureCase(
        "601138",
        "工业富联",
        PositionSnapshot(
            symbol="601138",
            name="工业富联",
            state="growing",
            health_score=55.0,
            previous_health=80.0,
            push_level=0,
        ),
        "warning",
        "T2",
    ),
    PositionFixtureCase(
        "601088",
        "中国神华",
        PositionSnapshot(
            symbol="601088",
            name="中国神华",
            state="growing",
            health_score=85.0,
            previous_health=85.0,
            push_level=0,
            held_for_days=200,
            narrative_label="entailment",
        ),
        "stable",
        "T1",
    ),
    PositionFixtureCase(
        "300866",
        "安克创新",
        PositionSnapshot(
            symbol="300866",
            name="安克创新",
            state="stable",
            health_score=55.0,
            previous_health=70.0,
            push_level=1,
        ),
        "warning",
        "T3",
    ),
    PositionFixtureCase(
        "601899",
        "紫金矿业",
        PositionSnapshot(
            symbol="601899",
            name="紫金矿业",
            state="stable",
            health_score=70.0,
            previous_health=70.0,
            push_level=1,
            narrative_label="contradiction",
        ),
        "warning",
        "T3",
    ),
    PositionFixtureCase(
        "600312",
        "平高电气",
        PositionSnapshot(
            symbol="600312",
            name="平高电气",
            state="stable",
            health_score=65.0,
            previous_health=65.0,
            push_level=1,
            narrative_invalid_count=3,
        ),
        "exit",
        "T4",
    ),
    PositionFixtureCase(
        "300308",
        "中际旭创",
        PositionSnapshot(
            symbol="300308",
            name="中际旭创",
            state="warning",
            health_score=25.0,
            previous_health=45.0,
            push_level=2,
        ),
        "exit",
        "T6",
    ),
    PositionFixtureCase(
        "300502",
        "新易盛",
        PositionSnapshot(
            symbol="300502",
            name="新易盛",
            state="warning",
            health_score=80.0,
            previous_health=70.0,
            push_level=2,
            health_above_75_days=10,
        ),
        "stable",
        "T5",
    ),
    PositionFixtureCase(
        "002837",
        "英维克",
        PositionSnapshot(
            symbol="002837",
            name="英维克",
            state="warning",
            health_score=40.0,
            previous_health=50.0,
            push_level=2,
            narrative_invalid_count=3,
        ),
        "exit",
        "T6",
    ),
    PositionFixtureCase(
        "300499",
        "高澜股份",
        PositionSnapshot(
            symbol="300499",
            name="高澜股份",
            state="growing",
            health_score=82.0,
            previous_health=80.0,
            push_level=0,
        ),
        "growing",
        None,
    ),
    PositionFixtureCase(
        "300602",
        "飞荣达",
        PositionSnapshot(
            symbol="300602",
            name="飞荣达",
            state="stable",
            health_score=72.0,
            previous_health=72.0,
            push_level=1,
        ),
        "stable",
        None,
    ),
]
