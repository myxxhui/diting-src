"""Z0-M2 政策 T1 Dispatcher · B1 逐篇 LLM 评分 → B2 三因子衰减聚合 → C 准入。

无降级策略：LLM 不可用直接报 error，不用关键词规则冒充语义结果。

[Ref: 36_ §4/§5/§7 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

POLICY_PROBE_KEY = "M.policy.sector_direction"
S0_SCOPE = "S0"
SCOPE_DOC = "S0_doc"
T1_SOURCE = "llm:deepseek-chat"

_LLM_CFG = (
    Path(__file__).resolve().parents[4]
    / "data" / "config" / "metrics" / "z0_policy_t1_llm.yaml"
)


def _load_llm_config() -> dict[str, Any]:
    if not _LLM_CFG.is_file():
        return {}
    with _LLM_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _sync_db_url() -> str:
    import os

    raw = (os.environ.get("COPILOT_DB_URL") or "sqlite+aiosqlite:///./data/copilot.db").strip()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return raw


# ──────────────────────────────────────────────
# §7 成本预估算
# ──────────────────────────────────────────────

def estimate_cost(
    pending_docs: list[dict[str, Any]],
    *,
    model: str = "deepseek-chat",
    daily_yuan_budget: float = 5.0,
) -> dict[str, Any]:
    """处理前成本预估算。"""
    cfg = _load_llm_config()
    pricing = (cfg.get("cost_control") or {}).get("pricing") or {}
    p = pricing.get(model) or {"input_per_1M_yuan": 1.0, "output_per_1M_yuan": 2.0}

    total_input = 0
    for doc in pending_docs:
        text_len = (
            len(str(doc.get("title") or ""))
            + len(str(doc.get("summary") or ""))
            + len(str(doc.get("full_text") or ""))
        )
        est = int(text_len * 0.28)  # 中文字符→token
        total_input += min(est, 8500)  # 按截断后

    est_output = len(pending_docs) * 400
    cost = (total_input / 1_000_000 * p["input_per_1M_yuan"]
            + est_output / 1_000_000 * p["output_per_1M_yuan"])

    return {
        "total_docs": len(pending_docs),
        "est_input_tokens": total_input,
        "est_output_tokens": est_output,
        "est_cost_yuan": round(cost, 4),
        "model": model,
        "within_daily_budget": cost <= daily_yuan_budget,
    }


# ──────────────────────────────────────────────
# §5.1 实施状态推断
# ──────────────────────────────────────────────

def _load_impl_status_keywords() -> dict[str, list[str]]:
    from apps.copilot.services.deepsea.policy_reader import load_policy_keywords
    cfg = load_policy_keywords()
    return cfg.get("impl_status_keywords") or {}


def infer_impl_status(text: str) -> str:
    """从标题+正文推断政策实施状态。"""
    keywords = _load_impl_status_keywords()
    # 优先级：废止 > 征求意见 > 已完成 > 待执行 > 进行中 > 未知
    for status, kws in [
        ("废止_替代", keywords.get("废止_替代") or []),
        ("征求意见稿", keywords.get("征求意见稿") or []),
        ("已执行_完成", keywords.get("已执行_完成") or []),
        ("已发布_待执行", keywords.get("已发布_待执行") or []),
        ("已执行_进行中", keywords.get("已执行_进行中") or []),
    ]:
        if any(kw in text for kw in kws):
            return status
    return "状态未知"


# ──────────────────────────────────────────────
# §5.1 时间衰减计算
# ──────────────────────────────────────────────

def _load_time_decay_config() -> dict[str, Any]:
    cfg = _load_llm_config()
    return cfg.get("time_decay") or {}


def _load_doc_type_weights() -> dict[str, float]:
    cfg = _load_llm_config()
    return cfg.get("doc_type_weights") or {}


def _load_impl_status_multipliers() -> dict[str, float]:
    cfg = _load_llm_config()
    return cfg.get("impl_status_multipliers") or {}


def compute_time_decay_weight(
    doc_type: str,
    days_since_published: int,
) -> float:
    """按文档类型计算时间衰减权重。"""
    decay_cfg = _load_time_decay_config()
    type_cfg = decay_cfg.get(doc_type, decay_cfg.get("L1", {}))
    fw = int(type_cfg.get("full_weight_days", 90))
    dtd = int(type_cfg.get("decay_to_days", 1095))
    mw = float(type_cfg.get("min_weight", 0.0))

    if days_since_published <= fw:
        return 1.0
    if days_since_published >= dtd:
        return mw
    # 线性衰减
    return round(1.0 - (days_since_published - fw) / (dtd - fw), 4)


def compute_composite_score(
    impact_score: float,
    doc_type: str,
    impl_status: str,
    days_since_published: int,
) -> float:
    """三因子加权：impact × W_type × M_status × D_time。"""
    w_type = _load_doc_type_weights().get(doc_type, 0.7)
    m_status = _load_impl_status_multipliers().get(impl_status, 0.6)
    d_time = compute_time_decay_weight(doc_type, days_since_published)
    return round(impact_score * w_type * m_status * d_time, 4)


# ──────────────────────────────────────────────
# §3 Phase A · 数据读取
# ──────────────────────────────────────────────

def _fetch_pending_docs(
    conn: Any,
    *,
    limit: int,
    lookback_days: int,
) -> list[dict[str, Any]]:
    """读取待处理的政策文档（含全文）。"""
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
        out.append({
            "doc_id": str(row["doc_id"]),
            "title": str(tags.get("title") or "")[:500],
            "summary": str(tags.get("summary") or tags.get("title") or "")[:2000],
            "full_text": str(tags.get("full_text") or ""),        # 新增：读取全文
            "source": str(tags.get("source") or ""),
            "feed_id": str(tags.get("feed_id") or ""),
            "feed_tier": str(tags.get("tier") or "L1"),            # 新增：读取 tier
            "published_at": row.get("published_at"),
            "object_uri": str(row.get("object_uri") or ""),
        })
    return out


# ──────────────────────────────────────────────
# §5 Phase B2 · 聚合 + 三因子衰减
# ──────────────────────────────────────────────

def _aggregate_with_decay(
    b1_results: list[dict[str, Any]],
    docs: list[dict[str, Any]],
    *,
    top_n: int = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """B2 三因子加权聚合。impl_status 使用 B1 LLM 推理结果（§5.0）。"""
    # doc_id → doc_meta
    doc_map: dict[str, dict[str, Any]] = {}
    for doc in docs:
        did = str(doc.get("doc_id") or "")
        if did:
            pub = doc.get("published_at")
            days = 0
            if pub:
                if isinstance(pub, datetime):
                    days = (datetime.now(timezone.utc).replace(tzinfo=None) - pub).days
                else:
                    days = 999

            doc_map[did] = {
                "doc_type": str(doc.get("feed_tier") or "L1"),
                "days_since_published": max(0, days),
                "title": str(doc.get("title") or ""),
            }

    sector_scores: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []

    for b1 in b1_results:
        did = str(b1.get("doc_id") or "")
        meta = doc_map.get(did, {})
        doc_type = str(meta.get("doc_type") or "L1")
        days = int(meta.get("days_since_published") or 0)

        # impl_status 来自 B1 LLM 推理（§5.0）
        llm_meta = b1.get("doc_metadata") or {}
        impl_status = str(llm_meta.get("impl_status") or "状态未知")
        if impl_status not in ("已发布_待执行", "已执行_进行中", "已执行_完成",
                               "征求意见稿", "废止_替代", "状态未知"):
            impl_status = "状态未知"  # fallback 防御

        for item in b1.get("sectors") or []:
            sector = str(item.get("sector_name") or "").strip()
            if not sector:
                continue

            impact = float(item.get("impact_score") or 0)
            effective = compute_composite_score(impact, doc_type, impl_status, days)
            w_total = (
                _load_doc_type_weights().get(doc_type, 0.7)
                * _load_impl_status_multipliers().get(impl_status, 0.6)
                * compute_time_decay_weight(doc_type, days)
            )

            bucket = sector_scores.setdefault(sector, {
                "sector": sector,
                "composite_score": 0.0,
                "total_weight": 0.0,
                "doc_count": 0,
                "tailwind_count": 0,
                "headwind_count": 0,
                "tailwind_weight": 0.0,
                "headwind_weight": 0.0,
            })
            bucket["composite_score"] += effective
            bucket["total_weight"] += w_total
            bucket["doc_count"] += 1

            direction = str(item.get("direction") or "neutral")
            if direction in ("strong_tailwind", "weak_tailwind"):
                bucket["tailwind_count"] += 1
                bucket["tailwind_weight"] += w_total
            elif direction in ("strong_headwind", "weak_headwind"):
                bucket["headwind_count"] += 1
                bucket["headwind_weight"] += w_total

            for quote in item.get("evidence_quotes") or []:
                evidence.append({
                    "sector": sector,
                    "doc_id": did,
                    "quote": quote[:300],
                    "direction": direction,
                })

    # 计算最终综合评分
    ranked: list[dict[str, Any]] = []
    for sector, bucket in sector_scores.items():
        tw = bucket["total_weight"]
        composite = round(bucket["composite_score"] / tw, 2) if tw > 0 else 0.0

        # 方向共识（加权投票）
        total_senti_w = bucket["tailwind_weight"] + bucket["headwind_weight"]
        if total_senti_w > 0:
            tw_ratio = bucket["tailwind_weight"] / total_senti_w
            hw_ratio = bucket["headwind_weight"] / total_senti_w
            if tw_ratio >= 0.8:
                consensus = "strong_tailwind"
            elif tw_ratio >= 0.6:
                consensus = "tailwind"
            elif hw_ratio >= 0.8:
                consensus = "strong_headwind"
            elif hw_ratio >= 0.6:
                consensus = "headwind"
            else:
                consensus = "mixed"
        else:
            consensus = "neutral"

        ranked.append({
            "sector": sector,
            "composite_score": composite,
            "consensus_direction": consensus,
            "doc_count": bucket["doc_count"],
            "tailwind_count": bucket["tailwind_count"],
            "headwind_count": bucket["headwind_count"],
        })

    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    return ranked[:top_n], evidence[:30]


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def _deduplicate_b1_sectors(sectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一文档内按 sector 去重，保留 score 最高的那条。"""
    seen: dict[str, dict[str, Any]] = {}
    for s in sectors:
        name = s.get("sector_name", "")
        if name in seen:
            if s.get("impact_score", 0) > seen[name].get("impact_score", 0):
                seen[name] = s
        else:
            seen[name] = s
    return list(seen.values())


def dispatch_policy_t1(
    *,
    limit: int = 200,
    lookback_days: int = 730,
    write_aggregate: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """T1 主入口：Phase A → B1(LLM) → B2(聚合衰减) → C(准入)。

    无降级策略：LLM 不可用或成本超预算直接报 error。
    """
    cfg = _load_llm_config()
    model = model or (cfg.get("llm_config") or {}).get("default_model", "deepseek-chat")
    daily_budget = float(
        (cfg.get("cost_control") or {}).get("daily_yuan_budget", 5.0)
    )

    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.begin() as conn:
            # Phase A：读取待处理文档
            pending = _fetch_pending_docs(conn, limit=limit, lookback_days=lookback_days)
            if not pending:
                return {
                    "status": "ok",
                    "detail": "无待处理的政策文档",
                    "processed": 0,
                    "source": T1_SOURCE,
                }

            # §7 成本预估算
            cost_est = estimate_cost(pending, model=model, daily_yuan_budget=daily_budget)
            if not cost_est["within_daily_budget"]:
                return {
                    "status": "error",
                    "detail": (
                        f"成本预估算超日预算：预估 ¥{cost_est['est_cost_yuan']} "
                        f"> 日预算 ¥{daily_budget}（{cost_est['total_docs']}篇 · "
                        f"~{cost_est['est_input_tokens']} input tokens）"
                    ),
                    "processed": 0,
                    "cost_estimate": cost_est,
                    "source": T1_SOURCE,
                }

            logger.info(
                "T1 成本预估算：%d 篇 · ~%d tokens · 预估 ¥%.4f · 预算内=%s",
                cost_est["total_docs"], cost_est["est_input_tokens"],
                cost_est["est_cost_yuan"], cost_est["within_daily_budget"],
            )

        # Phase B1：逐篇 LLM 评分（在连接外执行，不阻塞连接池）
        import asyncio

        from apps.copilot.services.deepsea.policy_t1_llm_scorer import dispatch_b1

        b1_successes, b1_errors = asyncio.run(dispatch_b1(pending, model=model))

        if not b1_successes:
            return {
                "status": "error",
                "detail": f"B1 LLM 评分全部失败（{len(b1_errors)}篇）",
                "processed": 0,
                "b1_errors": len(b1_errors),
                "errors": b1_errors[:5],
                "cost_estimate": cost_est,
                "source": T1_SOURCE,
            }

        if b1_errors:
            logger.warning("B1 部分失败：%d/%d 篇失败", len(b1_errors), len(pending))

        # Phase C：证据回检 + 去重
        from apps.copilot.services.deepsea.policy_t1_evidence_checker import (
            batch_check_evidence,
        )

        doc_map = {d["doc_id"]: d for d in pending}
        c_successes: list[dict[str, Any]] = []
        for b1 in b1_successes:
            did = b1.get("doc_id", "")
            doc = doc_map.get(did, {})
            ft = str(doc.get("full_text") or "")
            checked_sectors, all_passed = batch_check_evidence(b1.get("sectors") or [], ft)
            deduped = _deduplicate_b1_sectors(checked_sectors)
            c_successes.append({
                **b1,
                "sectors": deduped,
                "evidence_check_passed": all_passed,
            })

        # 写 DB（在连接内执行）
        processed = 0
        doc_snapshots: list[dict[str, Any]] = []
        with engine.begin() as conn:
            for sig in c_successes:
                did = sig.get("doc_id", "")
                inserted = _insert_policy_indicator_state(
                    conn, doc_id=did, signal=sig,
                )
                if inserted:
                    processed += 1
                    if sig.get("sectors"):
                        doc_snapshots.append(sig)

        # B2 聚合 + 写 S0 聚合
        aggregate: dict[str, Any] | None = None
        if write_aggregate and doc_snapshots:
            top_sectors, evidence = _aggregate_with_decay(
                doc_snapshots, pending, top_n=15,
            )
            if top_sectors:
                upsert_policy_indicator_state(
                    top_sectors=top_sectors,
                    evidence=evidence,
                    doc_id=None,
                    scope=S0_SCOPE,
                )
                aggregate = {"top_sectors": len(top_sectors), "scope": S0_SCOPE}

        return {
            "status": "ok" if processed > 0 else ("error" if b1_errors else "ok"),
            "detail": None if processed > 0 else "无新增政策文档",
            "processed": processed,
            "b1_errors": len(b1_errors) if b1_errors else None,
            "errors": b1_errors[:5] if b1_errors else None,
            "cost_estimate": cost_est,
            "aggregate": aggregate,
            "source": T1_SOURCE,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("政策 T1 dispatch 失败: %s", exc)
        return {
            "status": "error",
            "detail": f"T1 处理失败: {str(exc)[:300]}",
            "processed": 0,
            "source": T1_SOURCE,
        }
    finally:
        engine.dispose()


# ──────────────────────────────────────────────
#  DB 操作
# ──────────────────────────────────────────────

def _insert_policy_indicator_state(
    conn: Any,
    *,
    doc_id: str,
    signal: dict[str, Any],
) -> bool:
    """幂等写入 single-doc indicator_state。"""
    existing = conn.execute(
        text(
            "SELECT id FROM deepsea_indicator_state "
            "WHERE probe_key = :probe_key AND doc_id = :doc_id LIMIT 1"
        ),
        {"probe_key": POLICY_PROBE_KEY, "doc_id": doc_id},
    ).first()
    if existing:
        return False

    sectors = signal.get("sectors") or []
    direction = "neutral"
    if sectors:
        # 取 impact_score 最高的赛道方向
        top = max(sectors, key=lambda s: float(s.get("impact_score") or 0))
        direction = str(top.get("direction") or "neutral")

    evidence_quote = ""
    if sectors:
        for s in sectors:
            quotes = s.get("evidence_quotes") or []
            if quotes:
                evidence_quote = str(quotes[0])[:512]
                break

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    doc_meta = signal.get("doc_metadata") or {}
    snapshot = {
        "doc_id": doc_id,
        "title": signal.get("doc_id", ""),
        "policy_sectors": sectors,
        "overall_assessment": signal.get("overall_assessment", ""),
        "t1_source": signal.get("t1_source", T1_SOURCE),
        "llm_confidence": signal.get("llm_confidence", 0.0),
        "token_used": signal.get("token_used", 0),
        "evidence_check_passed": signal.get("evidence_check_passed", False),
        "impl_status": doc_meta.get("impl_status", "状态未知"),
        "impl_status_reasoning": doc_meta.get("impl_status_reasoning", ""),
    }

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
            "evidence_quote": evidence_quote,
            "momentum_delta": direction,
            "snapshot": json.dumps(snapshot, ensure_ascii=False),
            "doc_id": doc_id,
            "inferred_at": now,
        },
    )
    return True


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
    """T1 聚合落库（覆盖同 scope 旧聚合行）。"""
    import uuid

    _delete_aggregate_state(scope=scope)
    engine = create_engine(_sync_db_url(), future=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snapshot = {"top_sectors": top_sectors, "evidence": evidence or []}
    primary_direction = "neutral"
    if top_sectors:
        primary_direction = str(top_sectors[0].get("consensus_direction") or "neutral")
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
                    "evidence_quote": (evidence or [{}])[0].get("quote", "")[:512]
                    if evidence else "",
                    "momentum_delta": primary_direction,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                    "doc_id": doc_id or str(uuid.uuid4()),
                    "inferred_at": now,
                },
            )
    finally:
        engine.dispose()


__all__ = [
    "T1_SOURCE",
    "dispatch_policy_t1",
    "estimate_cost",
    "compute_time_decay_weight",
    "compute_composite_score",
    "infer_impl_status",
]
