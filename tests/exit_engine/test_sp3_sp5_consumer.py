"""SP3/SP5 Stream 消费逻辑单测（TEST_ONLY）。

[Ref: 03_/04_维度四/.../step_05 §7.1 B/I]
"""
from __future__ import annotations

import uuid

import pytest

from apps.exit_engine.db.init_db import init
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.position import HoldingORM
from apps.exit_engine.services.stream_consumer import (
    process_health_change,
    process_timer_signal,
)


@pytest.fixture
def db_session():
    init()
    db = SessionLocal()
    yield db
    db.close()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _seed_holding(db, symbol="002837", pos_id=None):
    pos_id = pos_id or _uid("pos")
    row = HoldingORM(
        id=pos_id,
        user_id="default",
        symbol=symbol,
        name="英维克",
        quantity=100,
        cost_price=40.0,
        current_price=38.0,
        is_active=True,
    )
    db.add(row)
    db.commit()
    return pos_id


def test_sp3_path_a_triggers(db_session):
    _seed_holding(db_session)
    msg_id = _uid("hc")
    r = process_health_change(
        db_session,
        {"symbol": "002837", "new_state": "exit", "event_id": msg_id},
        msg_id=msg_id,
    )
    assert r.handled is True
    assert r.triggered is True
    assert r.protocol == "SP3"


def test_sp3_path_b_triggers(db_session):
    _seed_holding(db_session)
    msg_id = _uid("hc")
    r = process_health_change(
        db_session,
        {
            "symbol": "002837",
            "narrative_label": "contradiction",
            "narrative_invalid_count": 3,
        },
        msg_id=msg_id,
    )
    assert r.triggered is True


def test_sp3_not_in_holdings_no_trigger(db_session):
    r = process_health_change(
        db_session,
        {"symbol": "999999", "new_state": "exit"},
        msg_id=_uid("hc"),
    )
    assert r.handled is True
    assert r.triggered is False


def test_sp3_idempotent(db_session):
    _seed_holding(db_session)
    payload = {"symbol": "002837", "new_state": "exit"}
    msg_id = _uid("hc-dup")
    r1 = process_health_change(db_session, payload, msg_id=msg_id)
    r2 = process_health_change(db_session, payload, msg_id=msg_id)
    assert r1.triggered is True
    assert r2.triggered is False
    assert r2.reason == "duplicate"


def test_sp5_main_wave_triggers(db_session):
    _seed_holding(db_session, symbol="300308")
    msg_id = _uid("ts")
    r = process_timer_signal(
        db_session,
        {
            "symbol": "300308",
            "stage": "main_wave",
            "evidence_url": "https://example.com/annual",
            "financial_report_date": "2026-08-15",
        },
        msg_id=msg_id,
    )
    assert r.handled is True
    assert r.triggered is True
    assert "持有" in (r.event.advice if r.event else "")


def test_sp5_three_stages(db_session):
    _seed_holding(db_session, symbol="300308")
    for stage in ("left_accumulate", "main_wave", "retreat"):
        r = process_timer_signal(
            db_session,
            {"symbol": "300308", "stage": stage},
            msg_id=_uid("ts-stage"),
        )
        assert r.triggered is True
