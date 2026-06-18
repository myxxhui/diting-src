"""Z0 政策 T1 Dispatcher · doc_registry → indicator_state enum 落库。

启动期：规则 enum（tailwind/headwind/neutral/mixed）+ sector_aliases 命中；
扩展期：同入口可换 LLM enum（禁止 mock）。

[Ref: 29_ §5.1 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text

from apps.copilot.services.deepsea.policy_reader import (
    POLICY_PROBE_KEY,
    S0_SCOPE,
    load_policy_keywords,
    upsert_policy_indicator_state,
)

logger = logging.getLogger(__name__)

T1_SOURCE = "rule:z0_policy_t1_v1"
SCOPE_DOC = "S0_doc"


def _sync_db_url() -> str:
    import os

    raw = (os.environ.get("COPILOT_DB_URL") or "sqlite+aiosqlite:///./data/copilot.db").strip()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return raw


def classify_direction(text: str, rules: dict[str, Any] | None = None) -> str:
    """顺逆风 enum · 规则版 T1。"""
    cfg = rules or load_policy_keywords().get("direction_rules") or {}
    allowed = set(cfg.get("enum_values") or ["tailwind", "headwind", "neutral", "mixed"])
    pos_kws = [str(k) for k in (cfg.get("tailwind") or [])]
    neg_kws = [str(k) for k in (cfg.get("headwind") or [])]
    pos = sum(1 for k in pos_kws if k and k in text)
    neg = sum(1 for k in neg_kws if k and k in text)
    if pos >= 1 and neg >= 1:
        direction = "mixed"
    elif pos > neg and pos >= 1:
        direction = "tailwind"
    elif neg > pos and neg >= 1:
        direction = "headwind"
    else:
        direction = "neutral"
    return direction if direction in allowed else "neutral"


def _weak_single_keywords(cfg: dict[str, Any] | None = None) -> set[str]:
    cfg = cfg or load_policy_keywords()
    return {str(k) for k in (cfg.get("weak_single_keywords") or []) if k}


def _sector_hit_valid(text: str, matched: list[str], weak: set[str]) -> bool:
    """过滤标题噪音：单关键词且属于 weak 列表则丢弃。"""
    if len(matched) >= 2:
        return True
    if len(matched) == 1:
        kw = matched[0]
        if kw in weak:
            return False
        if len(kw) >= 4:
            return True
        return kw not in weak
    return False


def match_sector_hits(text: str, aliases: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """按 sector_aliases 命中赛道 · 返回带 matched_keywords。"""
    cfg = load_policy_keywords()
    alias_map = aliases or cfg.get("sector_aliases") or {}
    weak = _weak_single_keywords(cfg)
    hits: list[dict[str, Any]] = []
    for sector, kws in alias_map.items():
        matched = [kw for kw in kws if kw and kw in text]
        if matched and _sector_hit_valid(text, matched, weak):
            hits.append({"sector": sector, "matched_keywords": matched})
    hits.sort(key=lambda x: len(x["matched_keywords"]), reverse=True)
    return hits


def _score_for_direction(direction: str, keyword_count: int) -> float:
    base = {"tailwind": 8.0, "mixed": 5.0, "neutral": 3.0, "headwind": 1.0}.get(direction, 3.0)
    return round(base + min(keyword_count, 5) * 0.5, 4)


def infer_doc_t1_snapshot(
    *,
    title: str,
    summary: str,
    doc_id: str,
    source: str = "",
    feed_id: str = "",
) -> dict[str, Any]:
    """单篇政策文档 T1 enum + sector 命中。"""
    text = f"{title}\n{summary}".strip()
    direction = classify_direction(text)
    sector_hits = match_sector_hits(text)
    top_sectors: list[dict[str, Any]] = []
    for hit in sector_hits:
        kw_n = len(hit["matched_keywords"])
        top_sectors.append(
            {
                "sector": hit["sector"],
                "direction": direction,
                "policy_score": _score_for_direction(direction, kw_n),
                "hit_count": 1,
                "matched_keywords": hit["matched_keywords"],
            }
        )
    return {
        "doc_id": doc_id,
        "title": title[:500],
        "source": source,
        "feed_id": feed_id,
        "direction": direction,
        "top_sectors": top_sectors,
        "evidence": [
            {
                "sector": s["sector"],
                "snippet": title[:200],
                "direction": direction,
                "matched_keywords": s.get("matched_keywords") or [],
            }
            for s in top_sectors
        ],
        "t1_source": T1_SOURCE,
    }


def _insert_doc_indicator_state(conn: Any, *, doc_id: str, snapshot: dict[str, Any]) -> bool:
    """幂等：同 doc_id + probe_key 已存在则 skip。"""
    existing = conn.execute(
        text(
            "SELECT id FROM deepsea_indicator_state "
            "WHERE probe_key = :probe_key AND doc_id = :doc_id LIMIT 1"
        ),
        {"probe_key": POLICY_PROBE_KEY, "doc_id": doc_id},
    ).first()
    if existing:
        return False

    direction = str(snapshot.get("direction") or "neutral")
    evidence = snapshot.get("evidence") or []
    quote = ""
    if evidence:
        quote = str(evidence[0].get("snippet") or "")[:512]
    elif snapshot.get("title"):
        quote = str(snapshot["title"])[:512]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
            "scope": SCOPE_DOC,
            "signal_status": direction,
            "evidence_quote": quote,
            "momentum_delta": direction,
            "snapshot": json.dumps(snapshot, ensure_ascii=False),
            "doc_id": doc_id,
            "inferred_at": now,
        },
    )
    return True


def _fetch_pending_docs(conn: Any, *, limit: int, lookback_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)
    rows = conn.execute(
        text(
            """
            SELECT d.doc_id, d.lineage_tags, d.published_at, d.object_uri
            FROM deepsea_doc_registry d
            LEFT JOIN deepsea_indicator_state s
              ON s.doc_id = d.doc_id AND s.probe_key = :probe_key
            WHERE d.doc_type = :doc_type
              AND s.id IS NULL
              AND (d.published_at IS NULL OR d.published_at >= :cutoff)
            ORDER BY COALESCE(d.published_at, d.created_at) DESC
            LIMIT :lim
            """
        ),
        {
            "probe_key": POLICY_PROBE_KEY,
            "doc_type": "policy",
            "cutoff": cutoff,
            "lim": limit,
        },
    ).mappings().all()

    out: list[dict[str, Any]] = []
    for row in rows:
        tags = row.get("lineage_tags") or {}
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = {}
        out.append(
            {
                "doc_id": str(row["doc_id"]),
                "title": str(tags.get("title") or ""),
                "summary": str(tags.get("summary") or ""),
                "source": str(tags.get("source") or ""),
                "feed_id": str(tags.get("feed_id") or ""),
                "object_uri": str(row.get("object_uri") or ""),
            }
        )
    return out


def _rollup_top_sectors(doc_snapshots: list[dict[str, Any]], *, top_n: int = 15) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """跨文档聚合 sector 分数与 evidence。"""
    sector_scores: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []

    for snap in doc_snapshots:
        for item in snap.get("top_sectors") or []:
            sector = str(item.get("sector") or "").strip()
            if not sector:
                continue
            bucket = sector_scores.setdefault(
                sector,
                {
                    "sector": sector,
                    "policy_score": 0.0,
                    "hit_count": 0,
                    "direction": item.get("direction"),
                    "tailwind_count": 0,
                    "headwind_count": 0,
                },
            )
            bucket["hit_count"] += 1
            bucket["policy_score"] = round(
                max(bucket["policy_score"], float(item.get("policy_score") or 0)),
                4,
            )
            direction = str(item.get("direction") or "neutral")
            if direction == "tailwind":
                bucket["tailwind_count"] += 1
            elif direction == "headwind":
                bucket["headwind_count"] += 1
            if bucket.get("direction") is None:
                bucket["direction"] = direction

        for ev in snap.get("evidence") or []:
            evidence.append({**ev, "doc_id": snap.get("doc_id")})

    for bucket in sector_scores.values():
        tc = int(bucket.get("tailwind_count") or 0)
        hc = int(bucket.get("headwind_count") or 0)
        if tc > hc:
            bucket["direction"] = "tailwind"
        elif hc > tc:
            bucket["direction"] = "headwind"
        elif tc >= 1 and hc >= 1:
            bucket["direction"] = "mixed"
        else:
            bucket["direction"] = bucket.get("direction") or "neutral"
        bucket["policy_score"] = round(
            bucket["policy_score"] + min(bucket["hit_count"], 10) * 0.2,
            4,
        )

    ranked = sorted(
        sector_scores.values(),
        key=lambda x: (
            int(x.get("tailwind_count") or 0),
            float(x.get("policy_score") or 0),
            int(x.get("hit_count") or 0),
        ),
        reverse=True,
    )
    # 启动期聚合：优先展示至少一篇 tailwind 命中的赛道，避免中性噪音霸榜
    ranked = [x for x in ranked if int(x.get("tailwind_count") or 0) >= 1] or ranked
    ranked = ranked[:top_n]
    return ranked, evidence[:30]


def dispatch_policy_t1(
    *,
    limit: int = 200,
    lookback_days: int = 730,
    write_aggregate: bool = True,
) -> dict[str, Any]:
    """T1：待处理 doc_registry 文档 → indicator_state enum + 可选 S0 聚合快照。"""
    engine = create_engine(_sync_db_url(), future=True)
    processed = 0
    skipped = 0
    no_sector = 0
    doc_snapshots: list[dict[str, Any]] = []

    try:
        with engine.begin() as conn:
            pending = _fetch_pending_docs(conn, limit=limit, lookback_days=lookback_days)
            for doc in pending:
                snap = infer_doc_t1_snapshot(
                    title=doc["title"],
                    summary=doc["summary"],
                    doc_id=doc["doc_id"],
                    source=doc["source"],
                    feed_id=doc["feed_id"],
                )
                if not snap.get("top_sectors"):
                    no_sector += 1
                    snap["top_sectors"] = []
                    snap["evidence"] = [
                        {
                            "sector": "",
                            "snippet": doc["title"][:200],
                            "direction": snap.get("direction"),
                            "matched_keywords": [],
                        }
                    ]
                inserted = _insert_doc_indicator_state(conn, doc_id=doc["doc_id"], snapshot=snap)
                if inserted:
                    processed += 1
                    if snap.get("top_sectors"):
                        doc_snapshots.append(snap)
                else:
                    skipped += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("政策 T1 dispatch 失败: %s", exc)
        return {
            "status": "error",
            "detail": str(exc)[:200],
            "processed": processed,
            "skipped": skipped,
            "source": T1_SOURCE,
        }
    finally:
        engine.dispose()

    aggregate: dict[str, Any] | None = None
    if write_aggregate and doc_snapshots:
        top_sectors, evidence = _rollup_top_sectors(doc_snapshots)
        if top_sectors:
            upsert_policy_indicator_state(
                top_sectors=top_sectors,
                evidence=evidence,
                doc_id=None,
                scope=S0_SCOPE,
            )
            aggregate = {"top_sectors": len(top_sectors), "scope": S0_SCOPE}

    status = "ok" if processed > 0 or skipped > 0 else "ok"
    return {
        "status": status,
        "detail": None if processed > 0 else "无待 T1 处理的 policy 文档",
        "processed": processed,
        "skipped": skipped,
        "no_sector_match": no_sector,
        "pending_before": processed + skipped + no_sector,
        "aggregate": aggregate,
        "source": T1_SOURCE,
    }


__all__ = [
    "T1_SOURCE",
    "classify_direction",
    "dispatch_policy_t1",
    "infer_doc_t1_snapshot",
    "match_sector_hits",
]
