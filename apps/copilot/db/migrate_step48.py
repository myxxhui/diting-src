"""step_48：DeepSea PG 契约表（doc_registry · indicator_state · indicator_config）。

[Ref: 29_ §5.1 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step48(engine: AsyncEngine) -> None:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS deepsea_doc_registry (
                        doc_id VARCHAR(36) PRIMARY KEY,
                        symbol TEXT,
                        doc_type TEXT NOT NULL,
                        object_uri TEXT,
                        parsed_uri TEXT,
                        published_at DATETIME,
                        lineage_tags JSON,
                        content_sha256 TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS deepsea_indicator_config (
                        probe_key TEXT PRIMARY KEY,
                        signal_type TEXT,
                        t1_pipeline TEXT,
                        update_trigger TEXT,
                        batch_id TEXT,
                        cache_group TEXT,
                        job_id TEXT,
                        t0_source_id TEXT,
                        state_machine JSON,
                        lineage_filter JSON,
                        tier TEXT,
                        cadence TEXT,
                        config_json JSON,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS deepsea_indicator_state (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        probe_key TEXT NOT NULL,
                        symbol TEXT,
                        scope TEXT,
                        signal_status TEXT,
                        evidence_quote TEXT,
                        momentum_delta TEXT,
                        snapshot JSON,
                        doc_id VARCHAR(36),
                        inferred_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_deepsea_indicator_state_probe "
                    "ON deepsea_indicator_state (probe_key, inferred_at)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_deepsea_doc_registry_type_pub "
                    "ON deepsea_doc_registry (doc_type, published_at)"
                )
            )
        logger.info("migrate_step48(sqlite): deepsea_* tables ensured")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS deepsea_doc_registry (
                    doc_id UUID PRIMARY KEY,
                    symbol TEXT,
                    doc_type TEXT NOT NULL,
                    object_uri TEXT,
                    parsed_uri TEXT,
                    published_at TIMESTAMPTZ,
                    lineage_tags JSONB,
                    content_sha256 TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS deepsea_indicator_config (
                    probe_key TEXT PRIMARY KEY,
                    signal_type TEXT,
                    t1_pipeline TEXT,
                    update_trigger TEXT,
                    batch_id TEXT,
                    cache_group TEXT,
                    job_id TEXT,
                    t0_source_id TEXT,
                    state_machine JSONB,
                    lineage_filter JSONB,
                    tier TEXT,
                    cadence TEXT,
                    config_json JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS deepsea_indicator_state (
                    id BIGSERIAL PRIMARY KEY,
                    probe_key TEXT NOT NULL,
                    symbol TEXT,
                    scope TEXT,
                    signal_status TEXT,
                    evidence_quote TEXT,
                    momentum_delta TEXT,
                    snapshot JSONB,
                    doc_id UUID,
                    inferred_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_deepsea_indicator_state_probe "
                "ON deepsea_indicator_state (probe_key, inferred_at DESC)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_deepsea_doc_registry_type_pub "
                "ON deepsea_doc_registry (doc_type, published_at DESC)"
            )
        )
    logger.info("migrate_step48(%s): deepsea_* tables ensured", dialect)
