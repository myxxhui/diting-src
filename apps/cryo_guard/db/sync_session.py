"""同步 Session（供采集脚本与离线校验使用）。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.cryo_guard.config import settings


def _sync_sqlite_url(async_url: str) -> str:
    if async_url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + async_url.removeprefix("sqlite+aiosqlite:///")
    if async_url.startswith("sqlite+aiosqlite://"):
        return "sqlite:///" + async_url.split("///", 1)[-1] if "///" in async_url else async_url.replace(
            "sqlite+aiosqlite:", "sqlite:"
        )
    return async_url


engine_sync = create_engine(_sync_sqlite_url(settings.db_url), echo=False, future=True)
SessionLocalSync = sessionmaker(bind=engine_sync, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocalSync()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
