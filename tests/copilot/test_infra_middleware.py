"""29_ 基础设施 · ARQ / DeepSea PG 单元测试。"""
from __future__ import annotations

import pytest


def test_arq_redis_dsn_derives_db1(monkeypatch):
    pytest.importorskip("arq")
    from apps.copilot.services.queue.settings import arq_redis_dsn

    monkeypatch.delenv("ARQ_REDIS_URL", raising=False)
    monkeypatch.setenv("COPILOT_REDIS_URL", "redis://localhost:6379/0")
    assert arq_redis_dsn().endswith("/1")


def test_retry_backoff_default():
    pytest.importorskip("arq")
    from apps.copilot.services.queue.settings import retry_backoff

    assert retry_backoff() == (5, 20, 60)


def test_deepsea_pg_ready_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "copilot.db"
    monkeypatch.setenv("COPILOT_DB_URL", f"sqlite+aiosqlite:///{db_path}")

    async def _migrate():
        from sqlalchemy.ext.asyncio import create_async_engine

        from apps.copilot.db.migrate_step48 import migrate_step48

        eng = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        await migrate_step48(eng)
        await eng.dispose()

    import asyncio

    asyncio.run(_migrate())
    from apps.copilot.services.deepsea.policy_reader import check_deepsea_pg_ready

    health = check_deepsea_pg_ready()
    assert health["status"] == "ok"
    assert health["tables"] == 3
