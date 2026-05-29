"""SP1/SP3/SP5 冲突优先级单测。

[Ref: 03_/04_维度四/.../step_05 §1 M]
"""
from __future__ import annotations

from apps.exit_engine.services.conflict_resolver import (
    AdviceRecord,
    partition_primary_secondary,
    records_from_events,
    sort_advices,
)


def test_sp1_primary_over_sp5():
    records = [
        AdviceRecord("SP5", "300308", "撤退期建议减仓", 2, {}),
        AdviceRecord("SP1", "300308", "止损建议清仓", 0, {}),
    ]
    primary, secondary = partition_primary_secondary(records)
    assert primary.protocol == "SP1"
    assert len(secondary) == 1
    assert secondary[0].protocol == "SP5"


def test_sp3_primary_over_sp5():
    records = [
        AdviceRecord("SP5", "300308", "主升浪建议持有", 2, {}),
        AdviceRecord("SP3", "300308", "thesis 失效建议清仓", 1, {}),
    ]
    primary, _ = partition_primary_secondary(records)
    assert primary.protocol == "SP3"


def test_sp1_sp3_sp5_all_recorded():
    events = [
        {"protocol": "SP5", "symbol": "300308", "advice": "a"},
        {"protocol": "SP1", "symbol": "300308", "advice": "b"},
        {"protocol": "SP3", "symbol": "300308", "advice": "c"},
    ]
    records = records_from_events(events)
    assert len(records) == 3
    ordered = sort_advices(records)
    assert ordered[0].protocol == "SP1"
