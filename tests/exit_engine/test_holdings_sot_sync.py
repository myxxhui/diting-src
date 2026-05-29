"""exit_engine 持仓 SoT 同步测试.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

import os
import tempfile
from textwrap import dedent

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.data.holdings_loader import sync_positions_from_sot
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.main import app
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


@pytest.fixture
def sot_yaml(tmp_path, monkeypatch):
    content = dedent(
        """
        holdings:
          - symbol: "603556"
            name: "海兴电力"
            active: true
            quantity: 1000
            cost_price: 25.5
          - symbol: "002270"
            name: "华明装备"
            active: true
            quantity: 500
            cost_price: 18.0
          - symbol: "999999"
            name: "已停用"
            active: false
            quantity: 100
            cost_price: 1.0
        defaults:
          crawl_years: [2024]
          throttle_sec: 0.6
        """
    ).strip()
    path = tmp_path / "my_holdings.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MY_HOLDINGS_YAML", str(path))
    return path


def test_sync_from_sot_upserts_active_only(session, sot_yaml):
    summary = sync_positions_from_sot(session)
    assert summary["synced"] == 2
    assert summary["active_symbols"] == ["002270", "603556"]
    repo = HoldingsRepository(session)
    rows = repo.list_active()
    assert len(rows) == 2
    symbols = {r.symbol for r in rows}
    assert symbols == {"603556", "002270"}


def test_sync_is_idempotent(session, sot_yaml):
    sync_positions_from_sot(session)
    again = sync_positions_from_sot(session)
    assert again["synced"] == 2
    assert len(HoldingsRepository(session).list_active()) == 2


def test_sync_deactivates_removed_symbols(session, sot_yaml, tmp_path, monkeypatch):
    sync_positions_from_sot(session)
    content = dedent(
        """
        holdings:
          - symbol: "603556"
            name: "海兴电力"
            active: true
            quantity: 1000
            cost_price: 25.5
        defaults:
          crawl_years: [2024]
        """
    ).strip()
    path = tmp_path / "reduced.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MY_HOLDINGS_YAML", str(path))
    summary = sync_positions_from_sot(session)
    assert summary["synced"] == 1
    assert summary["deactivated"] == 1
    rows = HoldingsRepository(session).list_active()
    assert len(rows) == 1
    assert rows[0].symbol == "603556"


def test_api_positions_sync_and_list(session, sot_yaml):
    from apps.exit_engine.routers.positions_router import get_db

    def _override_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            sync_resp = client.post("/api/positions/sync")
            assert sync_resp.status_code == 200
            body = sync_resp.json()
            assert body["synced"] == 2

            list_resp = client.get("/api/positions")
            assert list_resp.status_code == 200
            assert list_resp.json()["count"] == 2

            detail = client.get("/api/positions/603556")
            assert detail.status_code == 200
            assert detail.json()["symbol"] == "603556"
    finally:
        app.dependency_overrides.clear()


def test_reject_invalid_symbol(session, tmp_path, monkeypatch):
    content = dedent(
        """
        holdings:
          - symbol: "BAD"
            name: "无效"
            active: true
            quantity: 100
            cost_price: 10.0
        """
    ).strip()
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MY_HOLDINGS_YAML", str(path))
    summary = sync_positions_from_sot(session)
    assert summary["synced"] == 0
    assert summary["skipped"]


def test_watchlist_not_synced_to_exit_engine(session, tmp_path, monkeypatch):
    content = dedent(
        """
        holdings:
          - symbol: "603556"
            name: "海兴电力"
            active: true
            role: watchlist
            quantity: 0
            cost_price: 0
        """
    ).strip()
    path = tmp_path / "watchlist.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MY_HOLDINGS_YAML", str(path))
    summary = sync_positions_from_sot(session)
    assert summary["synced"] == 0
    assert summary["watchlist_symbols"] == ["603556"]


def test_mixed_portfolio_and_watchlist(session, tmp_path, monkeypatch):
    content = dedent(
        """
        holdings:
          - symbol: "601138"
            name: "工业富联"
            active: true
            role: portfolio
            quantity: 100
            cost_price: 50.0
          - symbol: "300308"
            name: "中际旭创"
            active: true
            role: watchlist
            quantity: 0
            cost_price: 0
        """
    ).strip()
    path = tmp_path / "mixed.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MY_HOLDINGS_YAML", str(path))
    summary = sync_positions_from_sot(session)
    assert summary["synced"] == 1
    assert summary["portfolio_symbols"] == ["601138"]
    assert summary["watchlist_symbols"] == ["300308"]
    rows = HoldingsRepository(session).list_active()
    assert len(rows) == 1
    assert rows[0].symbol == "601138"
