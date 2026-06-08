"""T1 指标节点 Schema 单测。

[Ref: 28_ §4.1]
"""
from __future__ import annotations

from apps.copilot.modules.executing.indicator_nodes import (
    SOURCE_INTRADAY_TICK,
    SOURCE_PG_EOD,
    build_qmt_atr_trailing_node,
)


def test_qmt_node_eod_objective_fact():
    node = build_qmt_atr_trailing_node(
        {
            "value": 3.06,
            "source": SOURCE_PG_EOD,
            "atr20": 4.7285,
            "peak_price": 84.95,
            "current": 70.48,
            "as_of": "2026-06-08",
            "entry_date_used": "2026-04-14",
        }
    )
    assert node["indicator_name"] == "动态ATR追踪止盈"
    assert node["value"] == 3.06
    assert "as_of" not in node
    assert "entry_date_used" not in node
    assert "atr20" not in node
    assert node["raw_metrics"]["atr_20"] == 4.73
    assert node["raw_metrics"]["peak_price"] == 84.95
    assert node["raw_metrics"]["current_price"] == 70.48
    assert "last_tick_time" not in node["raw_metrics"]
    assert node["raw_metrics"].get("bar_as_of") == "2026-06-08"
    assert node["calculation_logic"] == "(84.95 - 70.48) / 4.73 = 3.06"
    assert node["fact_statement"] == (
        "收盘价为 70.48，较持仓期绝对峰值 84.95 回撤 3.06 倍 ATR。"
    )
    assert "击穿" not in node["fact_statement"]
    assert "防线" not in node["fact_statement"]
    assert node["source"] == SOURCE_PG_EOD


def test_qmt_node_intraday_hot_data_slice():
    """盘中热数据推进时仅机械变更现价/时间戳/算式/value/fact。"""
    base = {
        "value": 1.00,
        "intraday": True,
        "atr20": 5.00,
        "peak_price": 85.00,
        "current": 80.00,
        "last_tick_time": "2026-06-08 10:00:00",
    }
    morning = build_qmt_atr_trailing_node(base)
    assert morning["value"] == 1.00
    assert morning["raw_metrics"]["current_price"] == 80.00
    assert morning["raw_metrics"]["last_tick_time"] == "2026-06-08 10:00:00"
    assert morning["raw_metrics"]["atr_20"] == 5.00
    assert morning["raw_metrics"]["peak_price"] == 85.00
    assert morning["calculation_logic"] == "(85.00 - 80.00) / 5.00 = 1.00"
    assert morning["fact_statement"] == (
        "盘中快照现价为 80.00，较持仓期绝对峰值 85.00 回撤 1.00 倍 ATR。"
    )
    assert morning["source"] == SOURCE_INTRADAY_TICK

    afternoon = build_qmt_atr_trailing_node(
        {
            **base,
            "value": 3.00,
            "current": 70.00,
            "last_tick_time": "2026-06-08 14:00:00",
        }
    )
    assert afternoon["value"] == 3.00
    assert afternoon["raw_metrics"]["current_price"] == 70.00
    assert afternoon["raw_metrics"]["last_tick_time"] == "2026-06-08 14:00:00"
    assert afternoon["raw_metrics"]["atr_20"] == 5.00
    assert afternoon["raw_metrics"]["peak_price"] == 85.00
    assert afternoon["calculation_logic"] == "(85.00 - 70.00) / 5.00 = 3.00"
    assert afternoon["fact_statement"] == (
        "盘中快照现价为 70.00，较持仓期绝对峰值 85.00 回撤 3.00 倍 ATR。"
    )
