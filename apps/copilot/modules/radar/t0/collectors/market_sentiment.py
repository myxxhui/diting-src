"""T0-1 全市场情绪量能。

[Ref: 27_ §2.2.1]
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call  # noqa: F401

logger = logging.getLogger(__name__)

REDIS_KEY = "radar:macro:market_sentiment:current"


def _today_cn() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def collect_market_sentiment_snapshot(*, finalized: bool = False) -> dict[str, Any]:
    """两市涨跌家数比 + 成交额（全 A 快照 · push2delay · 完善期：失败即 error）。"""
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_a_spot_snapshot
    from apps.copilot.modules.radar.t0.jobs.cache_merge import write_global_spot_cache

    snap = fetch_a_spot_snapshot()
    if snap.get("status") != "ok":
        return snap

    # 持久化全量行供 T0-7 同业（剥离 rows 避免 sentiment JSON 过大）
    write_global_spot_cache(snap)
    rows = snap.pop("rows", None)
    _ = rows

    snap["finalized"] = finalized
    if "collected_at" not in snap:
        from datetime import datetime, timezone

        snap["collected_at"] = datetime.now(timezone.utc).isoformat()
    return snap


def write_sentiment_redis(
    redis_client: Any,
    payload: dict[str, Any],
    *,
    ttl_sec: int = 7200,
    force: bool = False,
) -> None:
    """写入 Redis 热键；eod 定稿时 force=True 无视 TTL 强制覆盖。

    [Ref: 27_ §2.2.1]
    """
    if redis_client is None or payload.get("status") != "ok":
        return
    try:
        body = json.dumps(payload, ensure_ascii=False)
        if force or payload.get("finalized"):
            redis_client.set(REDIS_KEY, body)
            redis_client.expire(REDIS_KEY, ttl_sec)
        else:
            redis_client.setex(REDIS_KEY, ttl_sec, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis market_sentiment 写入失败: %s", exc)


async def read_sentiment_pg_latest(
    session: Any,
    *,
    before: date | None = None,
) -> dict[str, Any] | None:
    """最近一行已定稿日情绪（供 Scan 降级与环比计算）。

    [Ref: 27_ §2.2.1 Scan 读路径第 2 步]
    """
    from sqlalchemy import select

    from apps.copilot.db.models import RadarMarketSentimentDaily

    q = select(RadarMarketSentimentDaily).order_by(RadarMarketSentimentDaily.trade_date.desc()).limit(1)
    if before is not None:
        q = (
            select(RadarMarketSentimentDaily)
            .where(RadarMarketSentimentDaily.trade_date < before)
            .order_by(RadarMarketSentimentDaily.trade_date.desc())
            .limit(1)
        )
    row = (await session.scalars(q)).first()
    if row is None:
        return None
    snap = dict(row.snapshot_json or {})
    if snap.get("status") != "ok":
        snap = {
            "status": "ok",
            "trade_date": row.trade_date.isoformat(),
            "total_turnover_yi": row.total_turnover_yi,
            "exchange_turnover_yi": (row.snapshot_json or {}).get("exchange_turnover_yi"),
            "turnover_vs_prev_pct": row.turnover_vs_prev_pct,
            "advance_ratio": row.advance_ratio,
            "limit_up_height": row.limit_up_height,
            "source": row.source,
            "finalized": True,
        }
    else:
        snap.setdefault("trade_date", row.trade_date.isoformat())
        snap["finalized"] = True
    return snap


async def enrich_turnover_vs_prev(session: Any, payload: dict[str, Any]) -> None:
    """较上一交易日成交额环比%（27_ §2.2.1 · turnover_vs_prev_pct）。

    同比口径优先 ``exchange_turnover_yi``（与历史补录一致）；缺则回退 ``total_turnover_yi``。
    """
    if payload.get("status") != "ok":
        return
    td = payload.get("trade_date") or _today_cn().isoformat()
    trade_date = date.fromisoformat(str(td)[:10])

    if payload.get("exchange_turnover_yi") is None:
        from apps.copilot.modules.radar.t0.collectors.sentiment_backfill import (
            fetch_exchange_turnover_yi,
        )

        ex = await asyncio.to_thread(fetch_exchange_turnover_yi, trade_date)
        if ex is not None:
            payload["exchange_turnover_yi"] = ex

    today_turnover = payload.get("exchange_turnover_yi") or payload.get("total_turnover_yi")
    if today_turnover is None:
        return

    prev = await read_sentiment_pg_latest(session, before=trade_date)
    if not prev:
        payload["turnover_vs_prev_pct"] = None
        return
    prev_turnover = prev.get("exchange_turnover_yi") or prev.get("total_turnover_yi")
    if prev_turnover in (None, 0):
        payload["turnover_vs_prev_pct"] = None
        return
    try:
        payload["turnover_vs_prev_pct"] = round(
            (float(today_turnover) - float(prev_turnover)) / float(prev_turnover) * 100,
            2,
        )
    except (TypeError, ValueError):
        payload["turnover_vs_prev_pct"] = None


async def upsert_sentiment_pg(session: Any, payload: dict[str, Any]) -> None:
    if payload.get("status") != "ok":
        return
    from apps.copilot.db.models import RadarMarketSentimentDaily
    from apps.copilot.db.datetime_util import utc_now_naive

    td = payload.get("trade_date") or _today_cn().isoformat()
    trade_date = date.fromisoformat(str(td)[:10])
    row = await session.get(RadarMarketSentimentDaily, trade_date)
    if row is None:
        row = RadarMarketSentimentDaily(trade_date=trade_date)
        session.add(row)
    row.total_turnover_yi = payload.get("total_turnover_yi")
    row.turnover_vs_prev_pct = payload.get("turnover_vs_prev_pct")
    row.advance_ratio = payload.get("advance_ratio")
    row.limit_up_height = payload.get("limit_up_height")
    row.snapshot_json = payload
    row.finalized_at = utc_now_naive() if payload.get("finalized") else row.finalized_at
    row.source = payload.get("source")


def read_sentiment_redis(redis_client: Any) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(REDIS_KEY)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def load_macro_for_scan(redis_client: Any = None) -> dict[str, Any] | None:
    """扫描时注入 T0-1：Redis → PVC 文件（同步路径 · 无 PG）。"""
    snap = read_sentiment_redis(redis_client)
    if snap and snap.get("status") == "ok":
        return snap
    from apps.copilot.modules.radar.t0.jobs.cache_merge import read_global_macro_cache

    return read_global_macro_cache()


async def load_macro_for_scan_async(
    session: Any,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    """扫描时注入 T0-1：Redis → PVC → PG 最近定稿（27_ §2.2.1 完整读路径）。"""
    snap = load_macro_for_scan(redis_client)
    if snap and snap.get("status") == "ok":
        return snap
    return await read_sentiment_pg_latest(session)
