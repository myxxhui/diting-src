"""HoldingsRepository 单元测试.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.models.position import Base, Position


@pytest.fixture
def session():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        os.remove(path)


def test_upsert_and_list_active(session):
    repo = HoldingsRepository(session)
    p = Position(id="p1", symbol="600519", name="贵州茅台", quantity=100, cost_price=1800, current_price=1500)
    repo.upsert(p)
    rows = repo.list_active()
    assert len(rows) == 1
    assert rows[0].symbol == "600519"
    assert rows[0].return_pct == pytest.approx(-0.1667, rel=1e-2)


def test_bulk_update_quotes(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="600519", name="贵州茅台", quantity=100, cost_price=1800))
    repo.upsert(Position(id="p2", symbol="000858", name="五粮液", quantity=1000, cost_price=220))
    updated = repo.bulk_update_quotes({"600519": 1500.0, "000858": 187.0})
    assert updated == 2
    rows = {r.id: r for r in repo.list_active()}
    assert rows["p1"].current_price == 1500.0
    assert rows["p2"].current_price == 187.0
    assert rows["p1"].return_pct == pytest.approx(-0.1667, rel=1e-2)


def test_bulk_update_skips_unknown_or_zero(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="600519", name="贵州茅台", quantity=100, cost_price=1800))
    updated = repo.bulk_update_quotes({"600519": 0.0, "999999": 1.0})
    assert updated == 0


def test_deactivate(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="600519", name="贵州茅台", quantity=100, cost_price=1800))
    repo.deactivate(["p1"])
    assert repo.list_active() == []
