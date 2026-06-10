"""29_ 基础设施 · ARQ / OpenSearch 单元测试。"""
from __future__ import annotations

import pytest

from apps.copilot.services.queue.settings import arq_redis_dsn, retry_backoff
from apps.copilot.services.search import doc_retriever


def test_arq_redis_dsn_derives_db1(monkeypatch):
    monkeypatch.delenv("ARQ_REDIS_URL", raising=False)
    monkeypatch.setenv("COPILOT_REDIS_URL", "redis://localhost:6379/0")
    assert arq_redis_dsn().endswith("/1")


def test_retry_backoff_default():
    assert retry_backoff() == (5, 20, 60)


@pytest.mark.asyncio
async def test_opensearch_health_skipped_without_url(monkeypatch):
    monkeypatch.delenv("OPENSEARCH_URL", raising=False)
    monkeypatch.delenv("ES_URL", raising=False)
    health = await doc_retriever.check_opensearch_health()
    assert health["status"] == "skipped"


def test_make_doc_id_stable():
    doc_id = doc_retriever._make_doc_id(
        {
            "doc_type": "industry_news",
            "symbol": "601138",
            "theme": "cowos",
            "published_at": "2026-06-01",
            "source": "test",
            "title": "GB200",
        }
    )
    assert "601138" in doc_id
