"""ExitEngineOrchestrator 编排单测。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fakeredis import FakeRedis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.events.sell_signal_publisher import SellSignalPublisher
from apps.exit_engine.models.audit import ExitAuditORM  # noqa: F401
from apps.exit_engine.models.buffer import PendingSignalORM
from apps.exit_engine.models.position import Base, HoldingORM, Position, Portfolio
from apps.exit_engine.models.sell_signal_record import SellSignalRecordORM  # noqa: F401
from apps.exit_engine.models.sell_signal import SignalType
from apps.exit_engine.services.exit_engine_orchestrator import ExitEngineOrchestrator


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_stop_loss_holding(session, *, position_id: str = "p-sl", symbol: str = "601138"):
    session.add(
        HoldingORM(
            id=position_id,
            user_id="default",
            symbol=symbol,
            name="工业富联",
            quantity=100,
            cost_price=100.0,
            current_price=80.0,
            return_pct=-0.20,
            is_active=True,
        )
    )
    session.commit()
    return Position(
        id=position_id,
        symbol=symbol,
        name="工业富联",
        quantity=100,
        cost_price=100.0,
        current_price=80.0,
    )


def test_orchestrator_publishes_stop_loss(db_session):
    pos = _seed_stop_loss_holding(db_session)
    portfolio = Portfolio(user_id="default", positions=[pos], total_value=8000.0)
    fake = FakeRedis(decode_responses=True)
    orch = ExitEngineOrchestrator(
        db_session,
        publisher=SellSignalPublisher(redis_client=fake),
        publish=True,
    )
    result = orch.evaluate_position(pos, portfolio)
    assert result.winner is not None
    assert result.winner.signal_type == SignalType.STOP_LOSS
    assert result.published is True
    assert fake.xlen("events:exit:sell_signal") == 1
    assert result.conflict_audit_id


def test_orchestrator_no_publish_when_abstain(db_session):
    session = db_session
    session.add(
        HoldingORM(
            id="p-ok",
            user_id="default",
            symbol="600519",
            name="茅台",
            quantity=10,
            cost_price=1800.0,
            current_price=1900.0,
            return_pct=0.05,
            is_active=True,
        )
    )
    session.commit()
    pos = Position(
        id="p-ok", symbol="600519", name="茅台", quantity=10, cost_price=1800.0, current_price=1900.0
    )
    portfolio = Portfolio(user_id="default", positions=[pos], total_value=19_000.0)
    fake = FakeRedis(decode_responses=True)
    orch = ExitEngineOrchestrator(db_session, publisher=SellSignalPublisher(redis_client=fake), publish=True)
    result = orch.evaluate_position(pos, portfolio)
    assert result.winner is None
    assert result.published is False
    assert fake.xlen("events:exit:sell_signal") == 0


def test_orchestrator_expire_due_buffer(db_session):
    pos = _seed_stop_loss_holding(db_session, position_id="p-buf", symbol="300308")
    portfolio = Portfolio(user_id="default", positions=[pos], total_value=8000.0)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(
        PendingSignalORM(
            audit_id="audit-buf-1",
            protocol_name="take_profit",
            priority=2,
            position_id="p-buf",
            symbol="300308",
            trigger_price=130.0,
            triggered_price=135.0,
            sell_ratio=1.0,
            reason="buffer expired",
            advice="止盈到期",
            triggered_at=past,
            buffer_end_at=past,
            status="pending",
            user_id="default",
        )
    )
    db_session.commit()
    fake = FakeRedis(decode_responses=True)
    orch = ExitEngineOrchestrator(
        db_session,
        publisher=SellSignalPublisher(redis_client=fake),
        publish=True,
    )
    result = orch.evaluate_position(pos, portfolio, now=datetime.now(timezone.utc))
    assert result.winner is not None
    assert result.winner.signal_type == SignalType.STOP_LOSS
