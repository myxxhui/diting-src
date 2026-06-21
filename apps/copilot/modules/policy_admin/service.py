"""Z0 政策 T0 Admin 服务层 - 查询 deepsea_doc_registry 提供面板数据。

[Ref: 36_ §9 · z0_policy_feeds.yaml]
注意：所有 JSON 字段在 Python 层反序列化，避免 SQLite vs PostgreSQL JSON 语法差异。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


def _sync_db_url() -> str:
    import os

    raw = (
        os.environ.get("COPILOT_DB_URL") or "sqlite+aiosqlite:///./data/copilot.db"
    ).strip()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return raw


def _load_all_policy_docs() -> list[dict[str, Any]]:
    """加载所有 policy 类型文档，Python 层反序列化 lineage_tags。

    Returns:
        dicts with keys: doc_id, published_at, created_at, lineage_tags (parsed)
    """
    engine = create_engine(_sync_db_url(), future=True)
    docs: list[dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT doc_id, published_at, created_at, lineage_tags
                    FROM deepsea_doc_registry
                    WHERE doc_type = 'policy'
                    ORDER BY published_at DESC NULLS LAST, created_at DESC
                    """
                ),
            )
            for row in result:
                tags = row.lineage_tags
                if isinstance(tags, str):
                    tags = json.loads(tags)
                docs.append({
                    "doc_id": row.doc_id,
                    "published_at": row.published_at,
                    "created_at": row.created_at,
                    "lineage_tags": tags or {},
                })
    finally:
        engine.dispose()
    return docs


def get_source_health() -> list[dict[str, Any]]:
    """返回每个数据源的采集健康状态（Python 层聚合）。"""
    docs = _load_all_policy_docs()
    buckets: dict[str, dict[str, Any]] = {}
    for d in docs:
        tags = d["lineage_tags"]
        source = tags.get("source") or "unknown"
        if source not in buckets:
            buckets[source] = {
                "source": source,
                "total_docs": 0,
                "has_fulltext": 0,
                "last_published": None,
                "last_ingested": None,
                "has_recent": False,
            }
        b = buckets[source]
        b["total_docs"] += 1
        ft = tags.get("full_text")
        if ft:
            b["has_fulltext"] += 1
        pub = d["published_at"]
        if pub:
            if b["last_published"] is None or pub > b["last_published"]:
                b["last_published"] = pub
            # 近 7 天
            if pub >= datetime.now(timezone.utc).replace(tzinfo=None):
                b["has_recent"] = True
            elif hasattr(pub, "tzinfo"):
                # 处理可能有时区的问题
                pass
            # 简单判断：发表于7天内
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
            if isinstance(pub, datetime):
                try:
                    if (cutoff - pub).days <= 7:
                        b["has_recent"] = True
                except (TypeError, ValueError):
                    pass

        ingested = d["created_at"]
        if ingested and (
            b["last_ingested"] is None or ingested > b["last_ingested"]
        ):
            b["last_ingested"] = ingested

    return list(buckets.values())


def query_documents(
    source: str | None = None,
    sector: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """查询政策文档列表，Python 层过滤。

    Returns (docs, total_count).
    """
    all_docs = _load_all_policy_docs()
    # 过滤
    filtered: list[dict[str, Any]] = []
    for d in all_docs:
        tags = d["lineage_tags"]
        if source:
            if tags.get("source") != source:
                continue
        if sector:
            themes = tags.get("themes") or []
            if sector not in themes:
                continue
        filtered.append(d)

    total = len(filtered)
    sliced = filtered[offset : offset + limit]

    docs: list[dict[str, Any]] = []
    for d in sliced:
        tags = d["lineage_tags"]
        docs.append({
            "doc_id": d["doc_id"],
            "title": tags.get("title", ""),
            "source": tags.get("source", ""),
            "published_at": d["published_at"].isoformat() if d["published_at"] else None,
            "created_at": d["created_at"].isoformat() if d["created_at"] else None,
            "themes": tags.get("themes", []),
            "has_fulltext": bool(tags.get("full_text")),
            "full_text_len": tags.get("full_text_len", 0),
            "summary": tags.get("summary", ""),
            "link": tags.get("link", ""),
            "tier": tags.get("tier", ""),
        })
    return docs, total


def get_document_detail(doc_id: str) -> dict[str, Any] | None:
    """返回单篇文章完整信息（含全文）。"""
    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT doc_id, published_at, created_at, lineage_tags, object_uri, parsed_uri
                    FROM deepsea_doc_registry
                    WHERE doc_id = :doc_id
                    """
                ),
                {"doc_id": doc_id},
            ).first()
            if not row:
                return None
            tags = row.lineage_tags
            if isinstance(tags, str):
                tags = json.loads(tags)
            return {
                "doc_id": row.doc_id,
                "title": (tags or {}).get("title", ""),
                "source": (tags or {}).get("source", ""),
                "link": (tags or {}).get("link", row.object_uri),
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "themes": (tags or {}).get("themes", []),
                "full_text": (tags or {}).get("full_text", ""),
                "full_text_len": (tags or {}).get("full_text_len", 0),
                "summary": (tags or {}).get("summary", ""),
                "tier": (tags or {}).get("tier", ""),
                "feed_id": (tags or {}).get("feed_id", ""),
            }
    finally:
        engine.dispose()


def get_sector_source_matrix() -> dict[str, Any]:
    """按赛道×数据源汇聚文档数，返回矩阵数据。"""
    docs = _load_all_policy_docs()
    sectors: dict[str, dict[str, int]] = {}
    source_totals: dict[str, int] = {}
    for d in docs:
        tags = d["lineage_tags"]
        source = tags.get("source", "unknown")
        themes = tags.get("themes", []) or []
        source_totals.setdefault(source, 0)
        source_totals[source] += 1
        for theme in themes:
            if theme not in sectors:
                sectors[theme] = {}
            sectors[theme].setdefault(source, 0)
            sectors[theme][source] += 1

    tl_scores = _get_t1_sector_scores()
    return {
        "sectors": sectors,
        "source_totals": source_totals,
        "t1_scores": tl_scores,
    }


def _get_t1_sector_scores() -> dict[str, dict[str, Any]]:
    """从 deepsea_indicator_state 读取各赛道最新 T1 评分。"""
    engine = create_engine(_sync_db_url(), future=True)
    scores: dict[str, dict[str, Any]] = {}
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT metric_id, snapshot, updated_at
                    FROM deepsea_indicator_state
                    WHERE metric_id LIKE 'M.policy.sector_direction.%'
                    ORDER BY updated_at DESC NULLS LAST
                    LIMIT 100
                    """
                ),
            )
            seen: set[str] = set()
            for row in result:
                mid: str = row.metric_id
                if mid in seen:
                    continue
                seen.add(mid)
                snap = row.snapshot
                if isinstance(snap, str):
                    snap = json.loads(snap)
                sector_name = mid.replace("M.policy.sector_direction.", "")
                scores[sector_name] = {
                    "composite_score": snap.get("composite_score", 0),
                    "direction": snap.get("direction", "neutral"),
                    "doc_count": snap.get("doc_count", 0),
                    "generated_at": snap.get("generated_at", ""),
                }
    finally:
        engine.dispose()
    return scores


def get_event_timeline(
    days: int = 180,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """按时间线排列的政策文档。"""
    docs = _load_all_policy_docs()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    events: list[dict[str, Any]] = []
    for d in docs:
        pub = d["published_at"]
        if pub and isinstance(pub, datetime):
            try:
                if (now - pub).days > days:
                    continue
            except (TypeError, ValueError):
                continue
        tags = d["lineage_tags"]
        events.append({
            "doc_id": d["doc_id"],
            "title": tags.get("title", ""),
            "source": tags.get("source", ""),
            "published_at": pub.isoformat() if pub else None,
            "themes": tags.get("themes", []),
            "link": tags.get("link", ""),
            "tier": tags.get("tier", ""),
        })

    events.sort(key=lambda e: e["published_at"] or "", reverse=True)
    return events[:limit]


def get_all_sources() -> list[dict[str, Any]]:
    """合并配置中的数据源定义与 DB 中的实际采集状态。"""
    cfg_path = (
        Path(__file__).resolve().parents[4]
        / "data"
        / "config"
        / "metrics"
        / "z0_policy_feeds.yaml"
    )
    feed_defs: list[dict[str, Any]] = []
    if cfg_path.is_file():
        with cfg_path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        feed_defs = raw.get("feeds") or []

    db_stats = {s["source"]: s for s in get_source_health()}

    merged: list[dict[str, Any]] = []
    for fd in feed_defs:
        source_name = str(fd.get("source") or fd.get("id", ""))
        stats = db_stats.get(source_name, {})
        merged.append({
            "id": fd.get("id"),
            "name": fd.get("name", source_name),
            "kind": fd.get("kind", "rss"),
            "tier": fd.get("tier", "L1"),
            "url": fd.get("url", ""),
            "total_docs": stats.get("total_docs", 0),
            "has_fulltext": stats.get("has_fulltext", 0),
            "last_published": stats.get("last_published"),
            "last_ingested": stats.get("last_ingested"),
            "has_recent": stats.get("has_recent", False),
            "is_active": not str(fd.get("id", "")).startswith("_"),
        })

    # 加上 DB 中有但配置中已删除的源
    configured_sources = {fd.get("source") for fd in feed_defs if fd.get("source")}
    for src_name, stats in db_stats.items():
        if src_name not in configured_sources:
            merged.append({
                "id": f"orphan_{src_name}",
                "name": f"{src_name}（未配置）",
                "kind": "unknown",
                "tier": "unknown",
                "url": "",
                "total_docs": stats.get("total_docs", 0),
                "has_fulltext": stats.get("has_fulltext", 0),
                "last_published": stats.get("last_published"),
                "last_ingested": stats.get("last_ingested"),
                "has_recent": stats.get("has_recent", False),
                "is_active": False,
            })

    return merged
