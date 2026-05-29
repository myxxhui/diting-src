"""SQLAlchemy 会话工厂.[Ref: step_01]"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.exit_engine.config import settings

_engine = create_engine(settings.db_url_sync, echo=False, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Session:
    return SessionLocal()


def get_engine():
    return _engine
