"""quote_scheduler.refresh_quotes_once 单元测试.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.data.mock_quote_fetcher import MockQuoteFetcher
from apps.exit_engine.models.position import Base, Position
from apps.exit_engine.services import quote_scheduler


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(quote_scheduler, "SessionLocal", Session)
    yield Session
    os.remove(path)


def _seed(Session):
    s = Session()
    repo = HoldingsRepository(s)
    repo.upsert(Position(id="p1", symbol="600519", name="贵州茅台", quantity=100, cost_price=1800))
    repo.upsert(Position(id="p2", symbol="000858", name="五粮液", quantity=1000, cost_price=220))
    s.close()


def test_refresh_quotes_once_with_mock(temp_db):
    _seed(temp_db)
    mock = MockQuoteFetcher({"600519": 1500.0, "000858": 187.0})
    total, updated = quote_scheduler.refresh_quotes_once(user_id="default", fetcher=mock)
    assert total == 2
    assert updated == 2

    s = temp_db()
    repo = HoldingsRepository(s)
    rows = {r.id: r for r in repo.list_active()}
    s.close()
    assert rows["p1"].current_price == 1500.0
    assert rows["p2"].current_price == 187.0


def test_refresh_quotes_once_empty(temp_db):
    mock = MockQuoteFetcher({})
    total, updated = quote_scheduler.refresh_quotes_once(user_id="default", fetcher=mock)
    assert total == 0
    assert updated == 0


def test_refresh_quotes_once_partial(temp_db):
    _seed(temp_db)
    mock = MockQuoteFetcher({"600519": 1500.0})
    total, updated = quote_scheduler.refresh_quotes_once(user_id="default", fetcher=mock)
    assert total == 2
    assert updated == 1


def test_on_update_callback(temp_db):
    _seed(temp_db)
    mock = MockQuoteFetcher({"600519": 1500.0, "000858": 187.0})
    captured = {}

    def cb(quotes, updated):
        captured["quotes"] = quotes
        captured["updated"] = updated

    quote_scheduler.refresh_quotes_once(user_id="default", fetcher=mock, on_update=cb)
    assert captured["updated"] == 2
    assert "600519" in captured["quotes"]
