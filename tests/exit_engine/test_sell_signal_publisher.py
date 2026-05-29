"""SellSignalPublisher 单测。"""
from __future__ import annotations

import json

import pytest
from fakeredis import FakeRedis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.events.retry_worker import StreamRetryWorker
from apps.exit_engine.events.sell_signal_publisher import SellSignalPublisher
from apps.exit_engine.models.failed_publish import FailedStreamPublishORM
from apps.exit_engine.models.failed_publish import FailedStreamPublishORM  # noqa: F401
from apps.exit_engine.models.position import Base
from apps.exit_engine.models.sell_signal import SellSignalEvent, SignalSeverity, SignalType
from apps.exit_engine.models.sell_signal_record import SellSignalRecordORM


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def fake_redis():
    return FakeRedis(decode_responses=True)


def test_publish_xadd_and_record(db_session, fake_redis):
    pub = SellSignalPublisher(redis_client=fake_redis, stream_key="events:exit:sell_signal")
    event = SellSignalEvent(
        symbol="601138",
        signal_type=SignalType.STOP_LOSS,
        trigger_price=58.0,
        current_price=55.0,
        protocol="stop_loss",
        advice="止损建议",
        severity=SignalSeverity.EMERGENCY,
        position_id="p-601138",
    )
    msg_id = pub.publish(event, session=db_session, triggered_protocols=["stop_loss"])
    assert msg_id
    assert fake_redis.xlen("events:exit:sell_signal") == 1
    row = db_session.query(SellSignalRecordORM).filter_by(event_id=event.event_id).one()
    assert row.symbol == "601138"


def test_publish_failure_records_failed(db_session, monkeypatch):
    class BrokenRedis:
        def xadd(self, *args, **kwargs):
            raise ConnectionError("redis down")

    pub = SellSignalPublisher(redis_client=BrokenRedis())
    event = SellSignalEvent(
        symbol="X",
        signal_type=SignalType.STOP_LOSS,
        trigger_price=1.0,
        current_price=0.8,
        protocol="stop_loss",
        advice="a",
    )
    with pytest.raises(ConnectionError):
        pub.publish(event, session=db_session)
    failed = db_session.query(FailedStreamPublishORM).one()
    assert "redis down" in failed.error
    payload = json.loads(failed.payload)
    assert payload["symbol"] == "X"


def test_retry_worker(db_session, fake_redis):
    db_session.add(
        FailedStreamPublishORM(
            stream_key="events:exit:sell_signal",
            payload=json.dumps({"symbol": "R", "signal_type": "stop_loss", "advice": "x"}),
            error="timeout",
        )
    )
    db_session.commit()
    worker = StreamRetryWorker(db_session, redis_client=fake_redis)
    n = worker.retry_pending()
    assert n == 1
    assert fake_redis.xlen("events:exit:sell_signal") == 1
