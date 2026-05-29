"""SP1 止损协议测试.

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]
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
from apps.exit_engine.models.position import Base, Position
from apps.exit_engine.models.sell_signal import SignalSeverity, SignalType
from apps.exit_engine.protocols.stop_loss import StopLossProtocol
from apps.exit_engine.routers.protocol_router import get_db
from apps.exit_engine.services.protocol_runner import evaluate_and_audit


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


def _proto():
    return StopLossProtocol()


def test_boundary_negative_15_triggers(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=85.0))
    pos = repo.get("p1")
    r = evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    assert r.triggered is True
    assert r.signal is not None
    assert r.signal.sell_ratio == pytest.approx(1.0)


def test_boundary_negative_1499_no_trigger(session):
    repo = HoldingsRepository(session)
    repo.upsert(
        Position(id="p1", symbol="X", name="T", quantity=100, cost_price=1000.0, current_price=850.1)
    )
    pos = repo.get("p1")
    r = evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    assert r.triggered is False


def test_deep_loss_reason_contains_return(session):
    p = Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=70.0)
    proto = _proto()
    cr = proto.check(p, {})
    assert cr.triggered is True
    sig = proto.trigger(p, cr)
    assert "-30.00%" in sig.reason or "30.00%" in sig.reason


def test_cost_price_zero_abstain(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=100, cost_price=0.0, current_price=10.0))
    pos = repo.get("p1")
    r = evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    assert r.triggered is False


def test_quantity_zero_abstain(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=0, cost_price=100.0, current_price=50.0))
    pos = repo.get("p1")
    r = evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    assert r.triggered is False


def test_no_current_price_abstain(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0))
    pos = repo.get("p1")
    r = evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    assert r.triggered is False


def test_signal_meta_priority_buffer_sell_ratio_revocable(session):
    p = Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=80.0)
    proto = _proto()
    cr = proto.check(p, {})
    sig = proto.trigger(p, cr)
    assert sig.priority == 1
    assert sig.buffer_days == 0
    assert sig.sell_ratio == pytest.approx(1.0)
    assert sig.is_revocable is False


def test_audit_on_trigger(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=80.0))
    pos = repo.get("p1")
    evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    rows = list(session.scalars(select(ExitAuditORM)).all())
    assert len(rows) == 1
    assert rows[0].decision == "trigger"


def test_audit_on_abstain(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=99.0))
    pos = repo.get("p1")
    evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    rows = list(session.scalars(select(ExitAuditORM)).all())
    assert len(rows) == 1
    assert rows[0].decision == "abstain"


def test_output_event_emergency(session):
    p = Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=80.0)
    proto = _proto()
    cr = proto.check(p, {})
    sig = proto.trigger(p, cr)
    ev = proto.output_event(sig)
    assert ev.severity == SignalSeverity.EMERGENCY
    assert ev.signal_type == SignalType.STOP_LOSS


def test_evaluate_protocol_api(client, session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="X", name="T", quantity=100, cost_price=100.0, current_price=80.0))
    resp = client.post("/api/protocols/stop_loss/evaluate/p1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered"] is True
    assert body["event"] is not None


def test_positive_threshold_invalid():
    with pytest.raises(ValueError):
        StopLossProtocol(config={"stop_loss_threshold": 0.1})


def test_audit_lists_by_symbol(session):
    repo = HoldingsRepository(session)
    repo.upsert(Position(id="p1", symbol="SYM", name="T", quantity=100, cost_price=100.0, current_price=80.0))
    pos = repo.get("p1")
    evaluate_and_audit(_proto(), pos or Position("", "", "", 0, 0), session=session)
    from apps.exit_engine.services.audit_logger import AuditLogger

    logs = AuditLogger(session).list(symbol="SYM")
    assert len(logs) == 1
    assert logs[0].symbol == "SYM"
