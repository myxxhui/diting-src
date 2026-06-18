"""Z0 指标 Redis + PG 双写（热键 + 审计底库）。

[Ref: 29_ §4.2 · 34_ §3.0a]
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

REDIS_METRIC_PREFIX = "z0:metric:"
REDIS_WATERMARK_PREFIX = "z0:watermark:"
REDIS_PROGRESS_PREFIX = "z0:collect:progress:"


def metric_redis_key(metric_id: str) -> str:
    return f"{REDIS_METRIC_PREFIX}{metric_id}:latest"


def write_metric_redis(redis_client: Any, metric_id: str, payload: dict[str, Any], *, ttl_sec: int = 86400 * 7) -> None:
    if redis_client is None or payload.get("status") != "ok":
        return
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str)
        redis_client.setex(metric_redis_key(metric_id), ttl_sec, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Z0 metric Redis 写入失败 %s: %s", metric_id, exc)


def read_metric_redis(redis_client: Any, metric_id: str) -> Optional[dict[str, Any]]:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(metric_redis_key(metric_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def write_watermark_redis(redis_client: Any, job_id: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    try:
        redis_client.setex(
            f"{REDIS_WATERMARK_PREFIX}{job_id}",
            86400 * 30,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Z0 watermark Redis 写入失败 %s: %s", job_id, exc)


def read_watermark_redis(redis_client: Any, job_id: str) -> Optional[dict[str, Any]]:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(f"{REDIS_WATERMARK_PREFIX}{job_id}")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def set_collect_progress(redis_client: Any, run_id: str, payload: dict[str, Any], *, ttl_sec: int = 3600) -> None:
    if redis_client is None:
        return
    try:
        redis_client.setex(
            f"{REDIS_PROGRESS_PREFIX}{run_id}",
            ttl_sec,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Z0 progress Redis 写入失败: %s", exc)


async def upsert_metric_pg(session: AsyncSession, metric_id: str, payload: dict[str, Any]) -> None:
    from apps.copilot.db.models import Z0MetricSnapshot

    if payload.get("status") != "ok":
        return
    as_of_raw = payload.get("as_of") or payload.get("trade_date")
    as_of: Optional[datetime] = None
    if as_of_raw:
        if isinstance(as_of_raw, datetime):
            as_of = as_of_raw
        elif isinstance(as_of_raw, date):
            as_of = datetime.combine(as_of_raw, datetime.min.time(), tzinfo=timezone.utc)
        else:
            try:
                as_of = datetime.fromisoformat(str(as_of_raw)[:19]).replace(tzinfo=timezone.utc)
            except ValueError:
                as_of = datetime.now(timezone.utc)
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is not None:
        as_of = as_of.astimezone(timezone.utc).replace(tzinfo=None)

    row = Z0MetricSnapshot(
        metric_id=metric_id,
        as_of=as_of,
        payload_json=payload,
        status="ok",
    )
    session.add(row)


async def read_metrics_bundle(
    session: AsyncSession,
    redis_client: Any,
) -> dict[str, Any]:
    """读取段 A 合成所需最新指标（Redis 优先 · PG fallback）。"""
    from sqlalchemy import desc, select

    from apps.copilot.db.models import Z0MetricSnapshot

    ids = (
        "M.macro.pmi",
        "M.macro.cpi_ppi_spread",
        "M.macro.gdp_yoy",
        "M.macro.social_financing",
        "M.macro.m2_yoy",
        "M.macro.us10y",
        "M.macro.vix",
        "M.liq.north_net_20d",
        "M.liq.margin_balance",
        "M.liq.regime_composite",
        "M.sector.concept_heat",
        "M.sector.policy_direction",
    )
    out: dict[str, Any] = {}
    for mid in ids:
        snap = read_metric_redis(redis_client, mid)
        if snap and snap.get("status") == "ok":
            out[mid] = snap
            continue
        q = await session.execute(
            select(Z0MetricSnapshot)
            .where(Z0MetricSnapshot.metric_id == mid, Z0MetricSnapshot.status == "ok")
            .order_by(desc(Z0MetricSnapshot.as_of))
            .limit(1)
        )
        row = q.scalars().first()
        if row and row.payload_json:
            out[mid] = row.payload_json
    return out
