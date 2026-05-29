"""离线行情 mock,用于单元测试与无外网开发.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class MockQuoteFetcher:
    """简单 in-memory mock。"""

    DEFAULT_FIXTURE = (
        Path(__file__).resolve().parent.parent.parent.parent / "tests/exit_engine/fixtures/quotes_mock.json"
    )

    def __init__(self, prices: dict[str, float] | None = None):
        if prices is not None:
            self._prices = prices
        elif self.DEFAULT_FIXTURE.exists():
            self._prices = json.loads(self.DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        else:
            self._prices = {}

    def fetch_one(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def fetch_batch(self, symbols: list[str]) -> dict[str, float]:
        return {s: self._prices[s] for s in symbols if s in self._prices}

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price
