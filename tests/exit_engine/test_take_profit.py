"""SP2 止盈协议单元测试。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.main import app
from apps.exit_engine.models.audit import ExitAuditORM
from apps.exit_engine.models.buffer import PendingSignalORM
from apps.exit_engine.models.position import Base, Position
from apps.exit_engine.models.sell_signal import SignalSeverity, SignalType
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.routers.protocol_router import get_db


def _pos(cost=100.0, price=130.0, qty=100):
    return Position(id="p1", symbol="601318", name="中国平安", quantity=qty, cost_price=cost, current_price=price)


def test_constants():
    p = TakeProfitProtocol()
    assert p.protocol_name == SignalType.TAKE_PROFIT
    assert p.priority == 2
    assert p.buffer_days == 3
    assert p.threshold == pytest.approx(0.30)


def test_trigger_exact_30_percent():
    p = TakeProfitProtocol()
    signal = p.evaluate(_pos(100.0, 130.0))
    assert signal is not None
    assert signal.sell_ratio == 1.0
    assert signal.is_revocable is True
    assert signal.buffer_days == 3


def test_not_trigger_below_threshold():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(100.0, 129.99)) is None


def test_boundary_return_2999_no_trigger():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(1000.0, 1299.9)) is None


def test_boundary_return_3001_triggers():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(1000.0, 1300.1)) is not None


def test_trigger_above_threshold():
    p = TakeProfitProtocol()
    signal = p.evaluate(_pos(100.0, 130.01))
    assert signal is not None


def test_no_trigger_on_loss():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(100.0, 80.0)) is None


def test_no_trigger_on_flat():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(100.0, 100.0)) is None


def test_robust_against_missing_price():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(100.0, None)) is None


def test_robust_against_zero_cost():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(0.0, 130.0)) is None


def test_robust_against_zero_quantity():
    p = TakeProfitProtocol()
    assert p.evaluate(_pos(100.0, 130.0, qty=0)) is None


def test_custom_threshold_50_percent():
    p = TakeProfitProtocol(config={"take_profit_threshold": 0.50})
    assert p.evaluate(_pos(100.0, 130.0)) is None
    assert p.evaluate(_pos(100.0, 150.0)) is not None


def test_custom_sell_ratio_must_be_in_range():
    with pytest.raises(ValueError):
        TakeProfitProtocol(config={"take_profit_sell_ratio": 1.5})
    with pytest.raises(ValueError):
        TakeProfitProtocol(config={"take_profit_sell_ratio": 0})


def test_custom_buffer_days():
    p = TakeProfitProtocol(config={"take_profit_buffer_days": 5})
    assert p.buffer_days == 5


def test_negative_threshold_invalid():
    with pytest.raises(ValueError):
        TakeProfitProtocol(config={"take_profit_threshold": -0.1})


def test_output_event_buffer_end_at_set():
    p = TakeProfitProtocol()
    signal = p.evaluate(_pos(100.0, 130.0))
    assert signal is not None
    event = p.output_event(signal)
    assert event.severity == SignalSeverity.HIGH
    assert event.buffer_end_at is not None
    delta = event.buffer_end_at - event.triggered_at
    assert delta.days == 3


def test_is_reverse_condition_true_when_dropped():
    p = TakeProfitProtocol()
    assert p.is_reverse_condition(_pos(100.0, 125.0)) is True


def test_is_reverse_condition_false_when_still_above():
    p = TakeProfitProtocol()
    assert p.is_reverse_condition(_pos(100.0, 135.0)) is False


def test_is_reverse_condition_false_when_missing_price():
    p = TakeProfitProtocol()
    assert p.is_reverse_condition(_pos(100.0, None)) is False


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
def client(session):
    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_evaluate_take_profit_api(client, session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="601318", name="中国平安", quantity=100, cost_price=100.0, current_price=135.0))
    resp = client.post("/api/protocols/take_profit/evaluate/p1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered"] is True
    assert body["event"] is not None
    row = session.scalars(select(PendingSignalORM).where(PendingSignalORM.position_id == "p1")).first()
    assert row is not None
    assert row.status == "pending"


def test_evaluate_with_buffer_reverse_cancel_writes_audit(session):
    from apps.exit_engine.services.protocol_runner import evaluate_with_buffer

    repo = HoldingsRepository(session)
    repo.upsert(
        Position(id="p1", symbol="601318", name="中国平安", quantity=100, cost_price=100.0, current_price=135.0)
    )
    pos = repo.get("p1")
    proto = TakeProfitProtocol()
    evaluate_with_buffer(proto, pos or Position("", "", "", 0, 0), session=session)
    assert session.scalars(select(PendingSignalORM)).first() is not None

    repo.bulk_update_quotes({"601318": 125.0}, user_id="default")
    pos2 = repo.get("p1")
    evaluate_with_buffer(proto, pos2 or Position("", "", "", 0, 0), session=session)
    pend = session.scalars(select(PendingSignalORM).where(PendingSignalORM.position_id == "p1")).first()
    assert pend is not None
    assert pend.status == "cancelled"

    cancelled_audits = [
        r
        for r in session.scalars(select(ExitAuditORM)).all()
        if r.decision == "buffer_cancelled"
    ]
    assert len(cancelled_audits) >= 1
