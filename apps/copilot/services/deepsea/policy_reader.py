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
        return {"queries": [], "sector_aliases": {}, "canonical_sectors": {}}
    with _POLICY_CFG.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # v2.0 兼容：为依赖 sector_aliases 的旧代码生成该字段
    if not cfg.get("sector_aliases") and cfg.get("canonical_sectors"):
        cfg["sector_aliases"] = {
            name: sec.get("ingest_keywords") or []
            for name, sec in cfg["canonical_sectors"].items()
        }
    return cfg


def _match_sectors(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """返回匹配到的赛道名列表。"""
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
                    # T2 LLM 聚合使用 composite_score，旧规则使用 policy_score
                    score = float(item.get("composite_score") or item.get("policy_score") or 1.0)
                    doc_count = int(item.get("doc_count") or item.get("hit_count") or 1)
                    bucket = sector_scores.setdefault(
                        sector,
                        {
                            "sector": sector,
                            "policy_score": 0.0,
                            "hit_count": 0,
                            "direction": item.get("direction") or item.get("consensus_direction"),
                        },
                    )
                    bucket["hit_count"] = doc_count
                    bucket["policy_score"] = round(
                        max(bucket["policy_score"], score),
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


def read_sector_detail(sector: str, *, limit: int = 30) -> dict[str, Any]:
    """查询单个赛道的详细证据（T2 结论 + 文档原文引用 + 发布时间线）。"""
    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.connect() as conn:
            # 查询 S0 聚合行（T2 结论）
            agg = conn.execute(
                text(
                    """
                    SELECT snapshot, inferred_at, signal_status
                    FROM deepsea_indicator_state
                    WHERE probe_key = :probe_key AND scope = :scope
                    ORDER BY inferred_at DESC LIMIT 1
                    """
                ),
                {"probe_key": POLICY_PROBE_KEY, "scope": S0_SCOPE},
            ).mappings().first()

            sector_info: dict[str, Any] = {"sector": sector}
            if agg:
                snap_raw = agg.get("snapshot")
                if isinstance(snap_raw, str):
                    try:
                        snap_raw = json.loads(snap_raw)
                    except json.JSONDecodeError:
                        snap_raw = {}
                snapshot = snap_raw if isinstance(snap_raw, dict) else {}
                top = snapshot.get("top_sectors") or []
                for ts in top:
                    if isinstance(ts, dict) and ts.get("sector") == sector:
                        sector_info = {
                            "sector": sector,
                            "composite_score": ts.get("composite_score"),
                            "consensus_direction": ts.get("consensus_direction"),
                            "doc_count": ts.get("doc_count"),
                            "tailwind_count": ts.get("tailwind_count"),
                            "headwind_count": ts.get("headwind_count"),
                        }
                        break

                # 查询与赛道相关的政策文档证据（用 JSONB 在 DB 侧直接过滤）
                # v2.0: 同时匹配 sector_name 和 canonical_sector
                evidence_query = text(
                    """
                    SELECT s.snapshot, s.evidence_quote, s.signal_status, s.inferred_at, s.doc_id,
                           sec.value as matched_sector
                    FROM deepsea_indicator_state s,
                         jsonb_array_elements(s.snapshot -> 'policy_sectors') as sec
                    WHERE s.probe_key = :probe_key
                      AND s.scope = :scope_doc
                      AND (sec ->> 'sector_name' = :sector
                           OR sec ->> 'canonical_sector' = :sector)
                    ORDER BY s.inferred_at DESC
                    LIMIT :lim
                    """
                )
                doc_rows = conn.execute(
                    evidence_query,
                    {"probe_key": POLICY_PROBE_KEY, "scope_doc": "S0_doc", "sector": sector, "lim": limit},
                ).mappings().all()

                evidence_docs: list[dict[str, Any]] = []
                for row in doc_rows:
                    snap_raw = row.get("snapshot")
                    if isinstance(snap_raw, str):
                        try:
                            snap_raw = json.loads(snap_raw)
                        except json.JSONDecodeError:
                            continue
                    snapshot = snap_raw if isinstance(snap_raw, dict) else {}
                    # 取该文档中匹配到的 sector 对象
                    matched_raw = row.get("matched_sector")
                    if isinstance(matched_raw, str):
                        try:
                            matched_raw = json.loads(matched_raw)
                        except json.JSONDecodeError:
                            continue
                    s = matched_raw if isinstance(matched_raw, dict) else {}
                    quotes = s.get("evidence_quotes") or []
                    doc_title = snapshot.get("title") or row.get("doc_id") or ""
                    if len(doc_title) > 80:
                        doc_title = str(doc_title)[:80] + "..."
                    evidence_docs.append({
                        "doc_id": str(row.get("doc_id") or ""),
                        "title": doc_title,
                        "direction": s.get("direction", "neutral"),
                        "impact_score": s.get("impact_score"),
                        "evidence_quotes": [str(q)[:300] for q in quotes[:3]],
                        "reasoning": str(s.get("reasoning") or "")[:200],
                        "inferred_at": str(row.get("inferred_at") or ""),
                        "implementation_strength": s.get("implementation_strength"),
                        "implementation_toolkit": s.get("implementation_toolkit"),
                    })

                # 如果没有 T1 LLM 结果，回退到 doc_registry 标题匹配
                if not evidence_docs:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=730)
                    cfg = load_policy_keywords()
                    aliases: dict[str, list[str]] = cfg.get("sector_aliases") or {}
                    kws = aliases.get(sector, [sector])
                    doc_rows = conn.execute(
                        text(
                            """
                            SELECT doc_id, published_at, lineage_tags
                            FROM deepsea_doc_registry
                            WHERE doc_type = :doc_type
                              AND (published_at IS NULL OR published_at >= :cutoff)
                            ORDER BY published_at DESC
                            LIMIT :lim
                            """
                        ),
                        {"doc_type": POLICY_DOC_TYPE, "cutoff": cutoff.replace(tzinfo=None), "lim": limit},
                    ).mappings().all()

                    for doc in doc_rows:
                        tags = doc.get("lineage_tags") or {}
                        if isinstance(tags, str):
                            try:
                                tags = json.loads(tags)
                            except json.JSONDecodeError:
                                tags = {}
                        title = str(tags.get("title") or "")
                        if any(kw in title for kw in kws):
                            evidence_docs.append({
                                "doc_id": str(doc.get("doc_id") or ""),
                                "title": title[:80],
                                "direction": "neutral",
                                "impact_score": None,
                                "evidence_quotes": [],
                                "reasoning": "",
                                "published_at": str(doc.get("published_at") or ""),
                            })
                    evidence_docs = evidence_docs[:limit]

                sector_info["evidence_docs"] = evidence_docs
                sector_info["status"] = "ok"
            else:
                # 无 S0 聚合数据
                sector_info = {
                    "sector": sector,
                    "composite_score": None,
                    "consensus_direction": None,
                    "doc_count": 0,
                    "tailwind_count": 0,
                    "headwind_count": 0,
                    "evidence_docs": [],
                    "status": "no_data",
                }

            return sector_info
    except Exception as exc:  # noqa: BLE001
        logger.warning("赛道详情读取失败 sector=%s: %s", sector, exc)
        return {"sector": sector, "status": "error", "detail": str(exc)[:200]}
    finally:
        engine.dispose()


def compute_time_weighted_directions() -> dict[str, dict[str, Any]]:
    """对每个赛道，按时间衰减加权计算利好 vs 利空的方向得分。

    返回 dict[sector] = {
        net_direction: -1~+1（+1=全利好，-1=全利空）
        quality: composite_score / 100
        doc_count, tailwind_count, headwind_count
    }

    时效逻辑：每篇文档按 published_at 距今天数做时间衰减（L0/L1/L2/L3 不同衰减曲线），
    衰减后的 evidence_weight = impact_score × doc_type_weight × impl_status × time_decay
    """
    from datetime import datetime, timezone
    from pathlib import Path as _Path
    import math as _math

    cfg_path = _Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_t1_llm.yaml"
    cfg: dict[str, Any] = {}
    if cfg_path.is_file():
        with cfg_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    doc_w = cfg.get("source_authority") or {}
    if not doc_w:
        doc_w = cfg.get("doc_type_weights") or {}
    impl_m = cfg.get("impl_status_multipliers", {
        "已发布_待执行": 1.0, "已执行_进行中": 0.8, "已执行_完成": 0.3,
        "征求意见稿": 0.5, "废止_替代": 0.0, "状态未知": 0.6,
    })
    tdecay_cfg = cfg.get("time_decay", {})

    def _t_decay(doc_type: str, days: int) -> float:
        tc = tdecay_cfg.get(doc_type, tdecay_cfg.get("L1", {}))
        fw = int(tc.get("full_weight_days", 90))
        dtd = int(tc.get("decay_to_days", 1095))
        if days <= fw:
            return 1.0
        if days >= dtd:
            return 0.0
        return round(1.0 - (days - fw) / (dtd - fw), 4)

    engine = create_engine(_sync_db_url(), future=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with engine.connect() as conn:
            # 读取 S0 聚合以获得 composite_score 等
            agg = conn.execute(
                text(
                    "SELECT snapshot FROM deepsea_indicator_state "
                    "WHERE probe_key = :pk AND scope = :sc ORDER BY inferred_at DESC LIMIT 1"
                ),
                {"pk": POLICY_PROBE_KEY, "sc": S0_SCOPE},
            ).mappings().first()

            aggregate_sectors: dict[str, dict[str, Any]] = {}
            if agg:
                snap = agg["snapshot"]
                if isinstance(snap, str):
                    snap = json.loads(snap)
                for ts in (snap.get("top_sectors") or []):
                    aggregate_sectors[str(ts.get("sector", ""))] = ts

            # 读取所有 S0_doc 行 + 关联 doc_registry 获取发布时间
            doc_rows = conn.execute(
                text(
                    """
                    SELECT s.snapshot, d.published_at, d.lineage_tags
                    FROM deepsea_indicator_state s
                    JOIN deepsea_doc_registry d ON d.doc_id = s.doc_id
                    WHERE s.probe_key = :pk AND s.scope = :sc
                    """
                ),
                {"pk": POLICY_PROBE_KEY, "sc": "S0_doc"},
            ).mappings().all()

            # 按赛道累计
            from collections import defaultdict as _dd
            acc = _dd(lambda: {
                "bullish_w": 0.0, "bearish_w": 0.0, "total_w": 0.0, "high_value": False,
                "best_imp_strength": "symbolic",
                "toolkit": {k: 0.0 for k in ["fiscal_support", "talent_programs", "land_infra", "regulatory_fast_track", "standards_legislation", "quantitative_targets"]},
                "toolkit_count": 0,
            })

            for row in doc_rows:
                snap = row["snapshot"]
                if isinstance(snap, str):
                    snap = json.loads(snap)
                pub = row.get("published_at")
                days = (now - pub).days if pub else 999

                tags = row.get("lineage_tags") or {}
                if isinstance(tags, str):
                    try:
                        tags = json.loads(tags)
                    except json.JSONDecodeError:
                        tags = {}
                source = str(tags.get("source", "unknown"))

                doc_meta = snap.get("doc_metadata") or {}
                impl_status = str(doc_meta.get("impl_status", "状态未知"))

                td = _t_decay("L1", days)
                wd = doc_w.get(source, doc_w.get("default", 0.6))
                ms = impl_m.get(impl_status, 0.6)
                hv = bool(snap.get("high_value_flag"))

                for s in snap.get("policy_sectors") or []:
                    sn = str(s.get("sector_name", "")).strip()
                    canonical = str(s.get("canonical_sector", "")).strip()
                    if not sn:
                        continue
                    direction = str(s.get("direction", "neutral"))
                    impact = float(s.get("impact_score", 0))
                    ew = impact * wd * ms * td

                    # v2.1: 同时往 sector_name 和 canonical_sector 两个维度聚合
                    agg_keys = [sn]
                    if canonical and canonical.lower() != "null" and canonical != sn:
                        agg_keys.append(canonical)

                    for key in agg_keys:
                        if direction in ("strong_tailwind", "weak_tailwind"):
                            acc[key]["bullish_w"] += ew
                        elif direction in ("strong_headwind", "weak_headwind"):
                            acc[key]["bearish_w"] += ew
                        acc[key]["total_w"] += ew
                        if hv:
                            acc[key]["high_value"] = True

                        # 落地力度追踪
                        imp_str = str(s.get("implementation_strength") or "symbolic")
                        _imp_order = {"comprehensive": 5, "targeted": 4, "moderate": 3, "light": 2, "symbolic": 1}
                        if _imp_order.get(imp_str, 0) > _imp_order.get(acc[key]["best_imp_strength"], 0):
                            acc[key]["best_imp_strength"] = imp_str

                        # 累积实施工具包
                        toolkit = s.get("implementation_toolkit") or {}
                        if isinstance(toolkit, dict):
                            for k in acc[key]["toolkit"]:
                                acc[key]["toolkit"][k] += float(toolkit.get(k, 0))
                            acc[key]["toolkit_count"] += 1

            result: dict[str, dict[str, Any]] = {}
            max_dc = max((int(ts.get("doc_count", 1)) for ts in aggregate_sectors.values()), default=1)

            for sector, ts in aggregate_sectors.items():
                a = acc.get(sector, {"bullish_w": 0.0, "bearish_w": 0.0, "total_w": 0.0, "high_value": False, "toolkit": {}, "toolkit_count": 0})
                tw = a["total_w"]
                net = round((a["bullish_w"] - a["bearish_w"]) / max(tw, 0.01), 4)
                quality = round(float(ts.get("composite_score", 0)) / 100.0, 4)
                dc = int(ts.get("doc_count", 1))
                tcnt = int(ts.get("tailwind_count", 0))
                hcnt = int(ts.get("headwind_count", 0))
                confidence = round(_math.log(1 + dc) / _math.log(1 + max_dc), 4)
                purity = round((tcnt + hcnt) / max(dc, 1), 4)

                # 平均实施工具包（平均后0-10分）
                tc = max(a.get("toolkit_count", 1), 1)
                avg_toolkit = {
                    k: round(v / tc, 1)
                    for k, v in (a.get("toolkit") or {}).items()
                } if a.get("toolkit") else {}
                toolkit_total = sum(avg_toolkit.values()) if avg_toolkit else 0
                # implementation_bonus: 总分60→最多加30%
                impl_bonus = round(min(0.30, toolkit_total / 60 * 0.30), 4)

                # 落地力度多级系数（v5.1）
                from apps.copilot.services.deepsea.policy_t1_dispatcher import IMPLEMENTATION_FORCE_MULTIPLIER, IMPLEMENTATION_FORCE_LABELS
                imp_strength = a.get("best_imp_strength", "light")
                imp_mult = IMPLEMENTATION_FORCE_MULTIPLIER.get(imp_strength, 1.0)
                imp_label = IMPLEMENTATION_FORCE_LABELS.get(imp_strength, "方向性鼓励")

                result[sector] = {
                    "net_direction": net,
                    "quality": quality,
                    "doc_count": dc,
                    "tailwind_count": tcnt,
                    "headwind_count": hcnt,
                    "confidence": confidence,
                    "purity": purity,
                    "high_value_flag": a.get("high_value", False),
                    "imp_strength": imp_strength,
                    "imp_force_multiplier": imp_mult,
                    "imp_force_label": imp_label,
                    "avg_toolkit": avg_toolkit,
                    "toolkit_total": toolkit_total,
                    "implementation_bonus": impl_bonus,
                }

            return result
    except Exception:
        logger.exception("时间加权方向计算失败")
        return {}
    finally:
        engine.dispose()
