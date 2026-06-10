"""OpenSearch 长文检索 · T1 片段契约。

[Ref: 29_ §5 · §8]
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

INDEX_ALIAS = os.environ.get("OPENSEARCH_INDEX_ALIAS", "diting-docs-active")
INDEX_PREFIX = os.environ.get("OPENSEARCH_INDEX_PREFIX", "diting-docs-prod-v1")


def opensearch_url() -> str | None:
    return (
        os.environ.get("OPENSEARCH_URL")
        or os.environ.get("ES_URL")
        or os.environ.get("ELASTICSEARCH_URL")
    )


def _client():
    url = opensearch_url()
    if not url:
        return None
    from opensearchpy import OpenSearch

    return OpenSearch(
        hosts=[url],
        use_ssl=url.startswith("https"),
        verify_certs=False,
        ssl_show_warn=False,
        timeout=30,
    )


async def check_opensearch_health() -> dict[str, Any]:
    """§9 #7 · 集群 health；未配置 URL 时返回 skipped。"""
    url = opensearch_url()
    if not url:
        return {"status": "skipped", "error": "OPENSEARCH_URL 未配置"}

    def _ping() -> dict[str, Any]:
        client = _client()
        if client is None:
            return {"status": "skipped", "error": "客户端未初始化"}
        try:
            health = client.cluster.health()
            return {
                "status": health.get("status", "unknown"),
                "cluster_name": health.get("cluster_name"),
                "number_of_nodes": health.get("number_of_nodes"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)[:200]}

    return await asyncio_to_thread(_ping)


async def asyncio_to_thread(fn, *args, **kwargs):
    import asyncio

    return await asyncio.to_thread(fn, *args, **kwargs)


def ensure_index(client: Any) -> None:
    """最小可用索引 · 单节点无 ik 时用 standard 分词。"""
    if client.indices.exists(index=INDEX_PREFIX):
        if not client.indices.exists_alias(name=INDEX_ALIAS):
            client.indices.put_alias(index=INDEX_PREFIX, name=INDEX_ALIAS)
        return

    body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "doc_type": {"type": "keyword"},
                "symbol": {"type": "keyword"},
                "theme": {"type": "keyword"},
                "published_at": {"type": "date"},
                "source": {"type": "keyword"},
                "title": {"type": "text"},
                "body": {"type": "text"},
            }
        },
    }
    client.indices.create(index=INDEX_PREFIX, body=body)
    client.indices.put_alias(index=INDEX_PREFIX, name=INDEX_ALIAS)


async def index_document(doc: dict[str, Any]) -> str:
    """写入长文文档 · 返回 doc_id。"""
    url = opensearch_url()
    if not url:
        raise RuntimeError("OPENSEARCH_URL 未配置，无法索引长文")

    def _index() -> str:
        client = _client()
        assert client is not None
        ensure_index(client)
        payload = dict(doc)
        payload.setdefault("indexed_at", datetime.now(timezone.utc).isoformat())
        doc_id = payload.get("doc_id") or _make_doc_id(payload)
        payload["doc_id"] = doc_id
        client.index(index=INDEX_ALIAS, id=doc_id, body=payload, refresh="wait_for")
        return doc_id

    return await asyncio_to_thread(_index)


def _make_doc_id(doc: dict[str, Any]) -> str:
    base = "|".join(
        str(doc.get(k, ""))
        for k in ("doc_type", "symbol", "theme", "published_at", "source", "title")
    )
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", base)[:120]
    return slug or datetime.now(timezone.utc).strftime("doc_%Y%m%d_%H%M%S")


async def retrieve_fact_snippets(
    query: str,
    *,
    filters: dict[str, str] | None = None,
    max_chars: int = 1000,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """BM25 Top-K → fact_snippets[]（仅片段可进 T1/T2）。"""
    url = opensearch_url()
    if not url:
        logger.warning("OPENSEARCH_URL 未配置 · retrieve_fact_snippets 返回空")
        return []

    def _search() -> list[dict[str, Any]]:
        client = _client()
        assert client is not None
        must = [{"match": {"body": {"query": query, "operator": "and"}}}]
        if filters:
            for key, val in filters.items():
                if val:
                    must.append({"term": {key: val}})
        resp = client.search(
            index=INDEX_ALIAS,
            body={"query": {"bool": {"must": must}}, "size": top_k},
        )
        hits = resp.get("hits", {}).get("hits", [])
        out: list[dict[str, Any]] = []
        budget = max_chars
        for hit in hits:
            src = hit.get("_source") or {}
            body = str(src.get("body") or "")
            snippet = body[: min(len(body), budget)]
            if not snippet:
                continue
            budget -= len(snippet)
            out.append(
                {
                    "doc_id": src.get("doc_id") or hit.get("_id"),
                    "score": hit.get("_score"),
                    "snippet": snippet,
                    "source": src.get("source"),
                    "published_at": src.get("published_at"),
                }
            )
            if budget <= 0:
                break
        return out

    return await asyncio_to_thread(_search)
