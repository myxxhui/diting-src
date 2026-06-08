"""T1 探针 PG 快照与 #16 PG 回退单测。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.executing_render import render_smart_money_flow_card
from apps.copilot.modules.executing.indicator_nodes import build_smart_money_flow_node
from apps.copilot.modules.executing.storage import (
    load_t1_snapshot,
    upsert_t1_snapshot,
)
from apps.copilot.modules.executing.t1_assembler import _calc_volume_price_div_live


@pytest.mark.asyncio
async def test_upsert_and_load_t1_snapshot(db_session):
    node = build_smart_money_flow_node(
        {
            "value_pct": -0.71,
            "fact_statement": "测试",
            "calculation_logic": "logic",
            "raw_metrics": {"3d_smart_money_net_vol": -1000},
        },
        source="test",
    )
    await upsert_t1_snapshot(db_session, "601138", "smart_money_flow", node, source="test")
    await db_session.commit()
    loaded = await load_t1_snapshot(db_session, "601138", "smart_money_flow")
    assert loaded is not None
    assert loaded["value"] == -0.71
    assert loaded["indicator_name"] == "L2主力大单资金流向"


@pytest.mark.asyncio
async def test_volume_price_div_pg_fallback_from_bars_payload(db_session):
    raw_by_key = {
        "volume_price_div": {
            "ok": True,
            "source": "pg_test",
            "payload": {
                "bars_payload": {
                    "source": "pg_test",
                    "bars": [
                        {
                            "datetime": f"2026-06-01 10:{m:02d}:00",
                            "open": 80 + m * 0.01,
                            "close": 81 + m * 0.01,
                            "high": 82 + m * 0.01,
                            "low": 79 + m * 0.01,
                            "volume": 1000 + m,
                        }
                        for m in range(170)
                    ],
                }
            },
        }
    }
    key, node = await _calc_volume_price_div_live(
        db_session,
        "601138",
        redis_client=None,
        raw_by_key=raw_by_key,
    )
    assert key == "volume_price_div"
    assert node.get("value") is not None


def test_render_smart_money_flow_card():
    node = build_smart_money_flow_node(
        {
            "value_pct": -0.7144,
            "fact_statement": "近 3 个交易日内，大单与特大单累计净流出占自由流通盘的 0.71%。",
            "calculation_logic": "Sum(近3日大单+特大单净买入量) / 自由流通股本",
            "raw_metrics": {
                "3d_smart_money_net_vol": -71440,
                "free_float_shares": 10000000,
                "last_update_date": "20260606",
            },
        },
        source="Tushare API (moneyflow)",
    )
    html = render_smart_money_flow_card(node)
    assert "smart_money_flow" in html
    assert "L2主力大单" in html or "L2主力大单资金流向" in html
    assert "-0.7144" in html
