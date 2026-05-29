"""东财 push2 解析 fixture 测试。"""
from __future__ import annotations

from apps.common.market_quote.sources.eastmoney_list import parse_eastmoney_item


def test_parse_eastmoney_f2():
    q = parse_eastmoney_item({"f2": 6716, "f3": 252, "f12": "601138", "f14": "工业富联"})
    assert q is not None
    assert q.close == 67.16
    assert abs(q.change_pct - 2.52) < 0.001
    assert q.symbol == "601138"
    assert q.source == "eastmoney_list"
