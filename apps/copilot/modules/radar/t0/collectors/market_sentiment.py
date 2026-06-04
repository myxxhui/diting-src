"""T0-1 全市场情绪量能。

[Ref: 27_ §2.2.1]
"""
from __future__ import annotations

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


def write_sentiment_redis(redis_client: Any, payload: dict[str, Any], *, ttl_sec: int = 7200) -> None:
    if redis_client is None or payload.get("status") != "ok":
        return
    try:
        redis_client.setex(REDIS_KEY, ttl_sec, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis market_sentiment 写入失败: %s", exc)


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
    """扫描时注入 T0-1：Redis → 文件缓存。"""
    snap = read_sentiment_redis(redis_client)
    if snap and snap.get("status") == "ok":
        return snap
    from apps.copilot.modules.radar.t0.jobs.cache_merge import read_global_macro_cache

    return read_global_macro_cache()
