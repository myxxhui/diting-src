"""BufferManager 单元测试。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.models.buffer import PendingSignal
from apps.exit_engine.models.position import Base
from apps.exit_engine.services.buffer_manager import BufferManager


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


def _make(
    audit_id="a1",
    protocol="take_profit",
    position="p1",
    symbol="601318",
    buffer_days=3,
):
    now = datetime.utcnow()
    return PendingSignal(
        audit_id=audit_id,
        protocol_name=protocol,
        priority=2,
        position_id=position,
        symbol=symbol,
        trigger_price=44.2,
        triggered_price=45.0,
        sell_ratio=1.0,
        reason="收益率 +30% 触发",
        advice="缓冲 3 天",
        triggered_at=now,
        buffer_end_at=now + timedelta(days=buffer_days),
    )


def test_enqueue_new(session):
    bm = BufferManager(session)
    signal, is_new = bm.enqueue(_make())
    assert is_new is True
    assert signal.audit_id == "a1"
    assert bm.has_pending("p1", "take_profit") is True


def test_enqueue_idempotent(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1"))
    _, is_new = bm.enqueue(_make("a2"))
    assert is_new is False
    assert len(bm.list_pending()) == 1


def test_cancel(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1"))
    assert bm.cancel("a1", reason="manual") is True
    assert bm.has_pending("p1", "take_profit") is False


def test_cancel_missing_returns_false(session):
    bm = BufferManager(session)
    assert bm.cancel("missing", reason="x") is False


def test_cancel_by_position(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1"))
    n = bm.cancel_by_position("p1", "take_profit", reason="reverse")
    assert n == 1


def test_list_pending_filters(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1", position="p1"))
    bm.enqueue(_make("a2", position="p2"))
    bm.enqueue(_make("a3", protocol="rebalance", position="p3"))
    assert len(bm.list_pending()) == 3
    assert len(bm.list_pending(position_id="p1")) == 1
    assert len(bm.list_pending(protocol_name="take_profit")) == 2
    assert len(bm.list_pending(protocol_name="rebalance")) == 1


def test_expire_due_marks_fired(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1"))
    bm.enqueue(_make("a2", position="p2"))
    later = datetime.utcnow() + timedelta(days=4)
    fired = bm.expire_due(now=later)
    assert {f.audit_id for f in fired} == {"a1", "a2"}
    assert bm.list_pending() == []


def test_expire_due_skip_not_due(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1"))
    fired = bm.expire_due(now=datetime.utcnow())
    assert fired == []
    assert len(bm.list_pending()) == 1


def test_expire_due_skip_cancelled(session):
    bm = BufferManager(session)
    bm.enqueue(_make("a1"))
    bm.cancel("a1", reason="manual")
    later = datetime.utcnow() + timedelta(days=4)
    fired = bm.expire_due(now=later)
    assert fired == []
