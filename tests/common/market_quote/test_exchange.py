"""exchange 前缀分类测试。"""
from __future__ import annotations

import pytest

from apps.common.market_quote.exchange import (
    _em_prefix,
    _resolve_exchange,
    eastmoney_secid,
    tencent_code,
    validate_symbol,
)

PORTFOLIO = ["601138", "601088", "300866", "601899"]
WATCHLIST = ["600312", "300308", "300502", "002837", "300499", "300602"]

EXPECTED = {
    "601138": ("sh", "1", "sh601138", "1.601138"),
    "601088": ("sh", "1", "sh601088", "1.601088"),
    "300866": ("sz", "0", "sz300866", "0.300866"),
    "601899": ("sh", "1", "sh601899", "1.601899"),
    "600312": ("sh", "1", "sh600312", "1.600312"),
    "300308": ("sz", "0", "sz300308", "0.300308"),
    "300502": ("sz", "0", "sz300502", "0.300502"),
    "002837": ("sz", "0", "sz002837", "0.002837"),
    "300499": ("sz", "0", "sz300499", "0.300499"),
    "300602": ("sz", "0", "sz300602", "0.300602"),
}


@pytest.mark.parametrize("symbol", PORTFOLIO + WATCHLIST)
def test_exchange_classification(symbol: str):
    ex, em, tc, es = EXPECTED[symbol]
    assert _resolve_exchange(symbol) == ex
    assert _em_prefix(symbol) == em
    assert tencent_code(symbol) == tc
    assert eastmoney_secid(symbol) == es


def test_validate_symbol_rejects_bad():
    with pytest.raises(ValueError):
        validate_symbol("BAD")
