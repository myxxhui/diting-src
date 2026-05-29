"""新浪解析 fixture 测试。"""
from __future__ import annotations

from apps.common.market_quote.sources.sina import parse_sina_line

FIXTURE = (
    'var hq_str_sh601138="工业富联,66.110,65.500,67.160,67.660,64.500,67.160,67.170,'
    '194745516,12964388899.000,37744,44600,10700,18000,11500,10000,20000,15000,8000,'
    '9000,7000,6000,5000,4000,3000,2000,1000,500,2026-05-22,15:00:00";'
)


def test_parse_sina_line_close():
    q = parse_sina_line(FIXTURE)
    assert q is not None
    assert q.symbol == "601138"
    assert q.close == 67.160
    assert q.prev_close == 65.500
    assert q.source == "sina"
