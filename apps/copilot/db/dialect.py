"""数据库方言辅助（SQLite 本地 / PostgreSQL 生产）。"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql.dml import Insert

from apps.copilot.config import settings


def is_sqlite_url(url: str | None = None) -> bool:
    u = url or settings.db_url
    return "sqlite" in u


def dialect_insert(model) -> Insert:
    if is_sqlite_url():
        return sqlite_insert(model)
    return pg_insert(model)
