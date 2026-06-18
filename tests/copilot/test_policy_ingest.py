"""政策 T0 ingest 单元测试。"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from apps.copilot.services.deepsea.policy_ingest import register_policy_doc
from apps.copilot.services.deepsea.policy_reader import read_policy_sectors_from_pg


@pytest.fixture
def deepsea_sqlite(monkeypatch, tmp_path):
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

    asyncio.run(_migrate())
    yield db_path


def test_register_policy_doc_idempotent(deepsea_sqlite):
    url = f"https://example.gov.cn/policy/{uuid.uuid4()}"
    doc_id = register_policy_doc(
        url=url,
        title="关于加快算力基础设施建设的通知",
        summary="推动人工智能与算力产业高质量发展",
        source="test.gov.cn",
        feed_id="test",
        published_at=None,
    )
    assert doc_id
    again = register_policy_doc(
        url=url,
        title="关于加快算力基础设施建设的通知",
        summary="推动人工智能与算力产业高质量发展",
        source="test.gov.cn",
        feed_id="test",
        published_at=None,
    )
    assert again is None

    raw = read_policy_sectors_from_pg(top_n=5)
    assert raw["ok"] is True
    assert any(s["sector"] == "AI算力" for s in raw["top_sectors"])
