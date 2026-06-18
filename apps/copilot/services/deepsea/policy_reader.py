"""DeepSea 政策赛道 · PG 契约读取（Z0-M2 · 禁止 OpenSearch/BM25）。

[Ref: 29_ §5.1 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

POLICY_PROBE_KEY = "M.policy.sector_direction"
POLICY_DOC_TYPE = "policy"
S0_SCOPE = "S0"

_POLICY_CFG = (
    Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
)


def _sync_db_url() -> str:
    raw = (os.environ.get("COPILOT_DB_URL") or "sqlite+aiosqlite:///./data/copilot.db").strip()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return raw


def load_policy_keywords() -> dict[str, Any]:
    if not _POLICY_CFG.is_file():
        return {"queries": [], "sector_aliases": {}}
    with _POLICY_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _match_sectors(text: str, aliases: dict[str, list[str]]) -> list[str]:
    matched: list[str] = []
    for sector, kws in aliases.items():
        if any(kw in text for kw in kws):
            matched.append(sector)
    return matched


def _parse_snapshot_sectors(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not snapshot:
        return []
    if isinstance(snapshot.get("top_sectors"), list):
        return [s for s in snapshot["top_sectors"] if isinstance(s, dict) and s.get("sector")]
    sectors = snapshot.get("sectors")
    if isinstance(sectors, list):
        out: list[dict[str, Any]] = []
        for s in sectors:
            if isinstance(s, dict) and s.get("sector"):
                out.append(s)
            elif s:
                out.append({"sector": str(s), "policy_score": 1.0, "hit_count": 1})
        return out
    if snapshot.get("sector"):
        return [
            {
                "sector": str(snapshot["sector"]),
                "policy_score": float(snapshot.get("policy_score") or 1.0),
                "hit_count": int(snapshot.get("hit_count") or 1),
                "direction": snapshot.get("direction") or snapshot.get("signal_status"),
            }
        ]
    return []


def read_policy_sectors_from_pg(*, top_n: int = 10, lookback_days: int = 730) -> dict[str, Any]:
    """从 DeepSea PG 读取政策赛道 · T1 状态优先 · doc_registry 次之。"""
    engine = create_engine(_sync_db_url(), future=True)
    cfg = load_policy_keywords()
    aliases: dict[str, list[str]] = cfg.get("sector_aliases") or {}
    evidence: list[dict[str, Any]] = []
    sector_scores: dict[str, dict[str, Any]] = {}
    source_tag = "deepsea_doc_registry"

    try:
        with engine.connect() as conn:
            state_rows = conn.execute(
                text(
                    """
                    SELECT probe_key, scope, signal_status, evidence_quote, snapshot, doc_id, inferred_at
                    FROM deepsea_indicator_state
                    WHERE probe_key = :probe_key
                    ORDER BY inferred_at DESC, id DESC
                    LIMIT 200
                    """
                ),
                {"probe_key": POLICY_PROBE_KEY},
            ).mappings().all()

            aggregate_rows = [r for r in state_rows if r.get("scope") == S0_SCOPE]
            doc_rows = [r for r in state_rows if r.get("scope") == "S0_doc"]
            rows_to_read = aggregate_rows[:1] if aggregate_rows else doc_rows
            source_tag = (
                "deepsea_indicator_state:aggregate"
                if aggregate_rows
                else "deepsea_indicator_state:doc"
            )

            for row in rows_to_read:
                snap_raw = row.get("snapshot")
                if isinstance(snap_raw, str):
                    try:
                        snap_raw = json.loads(snap_raw)
                    except json.JSONDecodeError:
                        snap_raw = {}
                snapshot = snap_raw if isinstance(snap_raw, dict) else {}
                for item in _parse_snapshot_sectors(snapshot):
                    sector = str(item["sector"]).strip()
                    if not sector:
                        continue
                    bucket = sector_scores.setdefault(
                        sector,
                        {
                            "sector": sector,
                            "policy_score": 0.0,
                            "hit_count": 0,
                            "direction": item.get("direction"),
                        },
                    )
                    bucket["hit_count"] += int(item.get("hit_count") or 1)
                    bucket["policy_score"] = round(
                        max(bucket["policy_score"], float(item.get("policy_score") or 1.0)),
                        4,
                    )
                    if item.get("direction"):
                        bucket["direction"] = item.get("direction")
                    quote = row.get("evidence_quote") or item.get("evidence_quote") or ""
                    evidence.append(
                        {
                            "sector": sector,
                            "doc_id": row.get("doc_id"),
                            "snippet": str(quote)[:200],
                            "source": source_tag,
                            "inferred_at": str(row.get("inferred_at") or ""),
                            "direction": item.get("direction"),
                        }
                    )

            if not sector_scores:
                source_tag = "deepsea_doc_registry"
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                docs = conn.execute(
                    text(
                        """
                        SELECT doc_id, symbol, doc_type, published_at, lineage_tags, parsed_uri
                        FROM deepsea_doc_registry
                        WHERE doc_type = :doc_type
                          AND (published_at IS NULL OR published_at >= :cutoff)
                        ORDER BY published_at DESC
                        LIMIT 200
                        """
                    ),
                    {"doc_type": POLICY_DOC_TYPE, "cutoff": cutoff.replace(tzinfo=None)},
                ).mappings().all()

                for doc in docs:
                    tags = doc.get("lineage_tags") or {}
                    if isinstance(tags, str):
                        try:
                            tags = json.loads(tags)
                        except json.JSONDecodeError:
                            tags = {}
                    title = str(tags.get("title") or tags.get("headline") or "")
                    theme = str(tags.get("theme") or tags.get("sector") or "")
                    summary = str(tags.get("summary") or tags.get("abstract") or "")
                    text_blob = f"{title} {theme} {summary}"
                    sectors = _match_sectors(text_blob, aliases)
                    if not sectors and theme:
                        sectors = [theme]
                    for sector in sectors:
                        bucket = sector_scores.setdefault(
                            sector,
                            {"sector": sector, "policy_score": 0.0, "hit_count": 0},
                        )
                        bucket["hit_count"] += 1
                        bucket["policy_score"] = round(bucket["policy_score"] + 1.0, 4)
                        evidence.append(
                            {
                                "sector": sector,
                                "doc_id": doc.get("doc_id"),
                                "snippet": (title or summary)[:200],
                                "source": "deepsea_doc_registry",
                                "published_at": str(doc.get("published_at") or ""),
                            }
                        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("DeepSea PG 政策读取失败: %s", exc)
        return {
            "ok": False,
            "detail": f"DeepSea PG 读取失败: {exc}",
            "top_sectors": [],
            "evidence": [],
        }
    finally:
        engine.dispose()

    if not sector_scores:
        return {
            "ok": False,
            "detail": (
                "DeepSea PG 无政策数据（deepsea_indicator_state / deepsea_doc_registry 为空）"
                " · 待 T0 政策 ingest + T1 enum 落库"
            ),
            "top_sectors": [],
            "evidence": [],
        }

    ranked = sorted(
        sector_scores.values(),
        key=lambda x: (x["policy_score"], x["hit_count"]),
        reverse=True,
    )[:top_n]

    return {
        "ok": True,
        "detail": None,
        "top_sectors": ranked,
        "evidence": evidence[:20],
        "probe_key": POLICY_PROBE_KEY,
        "source_layer": source_tag,
    }


def _delete_aggregate_state(scope: str = S0_SCOPE) -> None:
    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM deepsea_indicator_state "
                    "WHERE probe_key = :probe_key AND scope = :scope"
                ),
                {"probe_key": POLICY_PROBE_KEY, "scope": scope},
            )
    finally:
        engine.dispose()


def upsert_policy_indicator_state(
    *,
    top_sectors: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
    doc_id: str | None = None,
    scope: str = S0_SCOPE,
) -> None:
    """T1 政策 enum 聚合落库 · 供 dispatcher 调用（覆盖同 scope 旧聚合行）。"""
    _delete_aggregate_state(scope=scope)
    engine = create_engine(_sync_db_url(), future=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snapshot = {"top_sectors": top_sectors, "evidence": evidence or []}
    primary_direction = "neutral"
    if top_sectors:
        primary_direction = str(top_sectors[0].get("direction") or "neutral")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO deepsea_indicator_state (
                        probe_key, symbol, scope, signal_status, evidence_quote,
                        momentum_delta, snapshot, doc_id, inferred_at
                    ) VALUES (
                        :probe_key, NULL, :scope, :signal_status, :evidence_quote,
                        :momentum_delta, :snapshot, :doc_id, :inferred_at
                    )
                    """
                ),
                {
                    "probe_key": POLICY_PROBE_KEY,
                    "scope": scope,
                    "signal_status": primary_direction,
                    "evidence_quote": (evidence or [{}])[0].get("snippet", "")[:512]
                    if evidence
                    else "",
                    "momentum_delta": primary_direction,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                    "doc_id": doc_id or str(uuid.uuid4()),
                    "inferred_at": now,
                },
            )
    finally:
        engine.dispose()


def check_deepsea_pg_ready() -> dict[str, Any]:
    """ARQ Worker 启动检查 · DeepSea 表是否存在。"""
    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.connect() as conn:
            for table in (
                "deepsea_doc_registry",
                "deepsea_indicator_state",
                "deepsea_indicator_config",
            ):
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        return {"status": "ok", "tables": 3}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        engine.dispose()
