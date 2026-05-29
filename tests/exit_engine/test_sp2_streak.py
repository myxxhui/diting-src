"""SP2 连续交易日缓冲单测.

[Ref: 03_/04_维度四/.../step_04_SP2止盈协议.md §3.5 L2~L5]
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.exit_engine.models.position import Base, Position
from apps.exit_engine.models.protocol_log import ProtocolLogORM
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.sp2_evaluator import evaluate_sp2_with_streak
from apps.exit_engine.services.sp2_streak import (
    buffer_state_label,
    count_consecutive_hits,
    evaluate_streak,
)


def test_buffer_state_pending_1_3():
    assert buffer_state_label(1, 3, hit_today=True) == "pending_1_3"


def test_buffer_state_pending_2_3():
    assert buffer_state_label(2, 3, hit_today=True) == "pending_2_3"


def test_buffer_state_triggered_day3():
    assert buffer_state_label(3, 3, hit_today=True) == "triggered"


def test_not_met_when_no_hit():
    assert buffer_state_label(0, 3, hit_today=False) == "not_met"


def test_consecutive_resets_after_miss():
    d1, d2, d3 = date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)
    hits = {d1: True, d2: False, d3: True}
    assert count_consecutive_hits(hits, date(2026, 5, 23)) == 1


def test_consecutive_three_days():
    d1, d2, d3 = date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)
    hits = {d1: True, d2: True, d3: True}
    assert count_consecutive_hits(hits, date(2026, 5, 23)) == 3


def test_evaluate_streak_day1_pending():
    state, trigger, streak = evaluate_streak(
        hit_today=True,
        hit_by_date={},
        trade_date=date(2026, 5, 20),
        buffer_days=3,
    )
    assert state == "pending_1_3"
    assert trigger is False
    assert streak == 1


def test_evaluate_streak_day3_triggers():
    d1, d2 = date(2026, 5, 18), date(2026, 5, 19)
    state, trigger, streak = evaluate_streak(
        hit_today=True,
        hit_by_date={d1: True, d2: True},
        trade_date=date(2026, 5, 20),
        buffer_days=3,
    )
    assert state == "triggered"
    assert trigger is True
    assert streak == 3


def test_evaluate_streak_interrupt_resets():
    d1 = date(2026, 5, 19)
    state, trigger, streak = evaluate_streak(
        hit_today=True,
        hit_by_date={d1: False},
        trade_date=date(2026, 5, 20),
        buffer_days=3,
    )
    assert state == "pending_1_3"
    assert trigger is False
    assert streak == 1


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


def test_sp2_evaluator_pending_then_trigger(session):
    pos = Position(
        id="p1",
        symbol="601318",
        name="中国平安",
        quantity=100,
        cost_price=100.0,
        current_price=135.0,
    )
    d1, d2, d3 = date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)
    r1 = evaluate_sp2_with_streak(pos, session=session, trade_date=d1)
    session.commit()
    assert r1.triggered is False
    log1 = session.scalars(select(ProtocolLogORM)).first()
    assert log1.buffer_state == "pending_1_3"

    r2 = evaluate_sp2_with_streak(pos, session=session, trade_date=d2)
    session.commit()
    logs = session.scalars(select(ProtocolLogORM).order_by(ProtocolLogORM.trade_date)).all()
    assert logs[-1].buffer_state == "pending_2_3"
    assert r2.triggered is False

    r3 = evaluate_sp2_with_streak(pos, session=session, trade_date=d3)
    session.commit()
    logs = session.scalars(select(ProtocolLogORM).order_by(ProtocolLogORM.trade_date)).all()
    assert logs[-1].buffer_state == "triggered"
    assert r3.triggered is True


def test_sp2_yaml_load():
    from apps.exit_engine.protocol_config import load_sp2_config

    cfg = load_sp2_config()
    assert cfg.get("take_profit_threshold") == pytest.approx(0.30)
    assert cfg.get("take_profit_buffer_days") == 3
