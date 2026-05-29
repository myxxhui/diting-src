"""腾讯解析 fixture 测试。"""
from __future__ import annotations

from apps.common.market_quote.sources.tencent import parse_tencent_line

FIXTURE = (
    'v_sh601138="1~工业富联~601138~67.16~65.50~66.11~1947455~1144963~802492~'
    '67.16~377~67.15~446~67.14~107~67.13~180~67.12~115~67.11~100~67.10~200~'
    '67.09~150~67.08~80~67.07~90~67.06~70~67.05~60~67.04~50~67.03~40~'
    '67.02~30~67.01~20~2026-05-22~15:30:00";'
)


def test_parse_tencent_line_close():
    q = parse_tencent_line(FIXTURE)
    assert q is not None
    assert q.symbol == "601138"
    assert q.close == 67.16
    assert q.prev_close == 65.50
    assert q.source == "tencent"
    assert q.volume == 1947455 * 100
