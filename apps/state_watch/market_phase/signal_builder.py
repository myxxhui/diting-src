"""拉取 P3/P4/P2/物理探针信号，供 rule_classifier 使用."""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from apps.common.holdings_sot import HoldingEntry
from apps.state_watch.market_phase.schemas import PhaseSignals
from apps.state_watch.probes.datasource.quote_adapter import Bar, fetch_bars_60d
from apps.state_watch.probes.event import EventProbe
from apps.state_watch.probes.news import NewsProbe
from apps.state_watch.probes.price import compute_price_metrics, _ma
from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

logger = logging.getLogger(__name__)

_POSITIVE_ANN = ("业绩", "预告", "快报", "合同", "中标", "战略", "年报", "半年报", "季报")
_Q_REPORT = ("年报", "半年报", "一季报", "三季报", "季报")
_PRE_ANN = ("预告", "业绩预告", "业绩快报")
_CONTRACT = ("合同", "中标", "订单", "签约")


def _cryo_db_path() -> Path:
    env = os.environ.get("CRYO_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data" / "cryo_guard.db"


def _pct_change(closes: list[float], days: int) -> float | None:
    if len(closes) <= days:
        return None
    base = closes[-(days + 1)]
    last = closes[-1]
    if base <= 0:
        return None
    return (last / base) - 1.0


def extended_price_metrics(bars: list[Bar]) -> dict[str, Any]:
    if len(bars) < 2:
        return {"insufficient_price": True}
    base = compute_price_metrics(bars)
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    vol5 = sum(volumes[-5:]) / min(5, len(volumes[-5:])) if volumes else 0.0
    window = min(60, len(volumes))
    vol60 = sum(volumes[-window:]) / window if window else 0.0
    vol_ratio_5d = (vol5 / vol60) if vol60 > 0 else 1.0
    ma10 = _ma(closes, 10)
    last = closes[-1]
    return {
        **base,
        "pct_chg_3d": _pct_change(closes, 3),
        "pct_chg_5d": _pct_change(closes, 5),
        "pct_chg_30d": _pct_change(closes, 30),
        "pct_chg_60d": _pct_change(closes, min(60, len(closes) - 1)),
        "volume_ratio_5d": round(vol_ratio_5d, 4),
        "price_below_ma10": bool(ma10 > 0 and last < ma10),
        "insufficient_price": False,
    }


def _announcement_flags(symbol: str, window_days: int = 5) -> dict[str, bool]:
    db = _cryo_db_path()
    out = {
        "has_q_report_released": False,
        "has_pre_announce_released": False,
        "has_major_contract": False,
        "no_announcement_positive": True,
        "latest_positive_date": None,
    }
    if not db.is_file():
        out["tags"] = ["cryo_db_absent"]
        return out
    cutoff = (datetime.utcnow() - timedelta(days=window_days)).date().isoformat()
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            """
            SELECT ann_type, ann_date, title FROM announcements
            WHERE symbol = ? AND ann_date >= ?
            ORDER BY ann_date DESC LIMIT 50
            """,
            (symbol, cutoff),
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.warning("announcements read failed %s: %s", symbol, exc)
        return out

    for ann_type, ann_date, title in rows:
        text = f"{ann_type or ''} {title or ''}"
        if not any(k in text for k in _POSITIVE_ANN):
            continue
        out["no_announcement_positive"] = False
        if any(k in text for k in _Q_REPORT):
            out["has_q_report_released"] = True
        if any(k in text for k in _PRE_ANN):
            out["has_pre_announce_released"] = True
        if any(k in text for k in _CONTRACT):
            out["has_major_contract"] = True
        if out["latest_positive_date"] is None:
            out["latest_positive_date"] = str(ann_date)
    return out


def _phys_probe_active_count(symbol: str) -> int:
    try:
        import redis

        from dotenv import load_dotenv

        repo = Path(__file__).resolve().parents[3]
        load_dotenv(repo / ".env", override=False)
        url = os.getenv("STATE_WATCH_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/3")
        client = redis.from_url(url, decode_responses=True)
        client.ping()
        reader = MonitorDictReader(client)
        if not reader.has_dict(symbol):
            return 0
        active = 0
        for fld in reader.all_active_fields(symbol):
            if fld.probe_id not in ("P5", "P6", "P7"):
                continue
            raw = client.get(fld.raw_key)
            if not raw:
                continue
            try:
                import json

                payload = json.loads(raw)
                hit = payload.get("last_hit_at")
                if not hit:
                    continue
                dt = datetime.fromisoformat(str(hit).replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).days <= 14:
                    active += 1
            except (ValueError, TypeError):
                active += 1
        return active
    except Exception:
        return 0


async def build_signals(entry: HoldingEntry) -> PhaseSignals:
    sym = entry.symbol.zfill(6)[-6:]
    tags: list[str] = []

    try:
        bars = await asyncio.wait_for(asyncio.to_thread(fetch_bars_60d, sym), timeout=15.0)
    except asyncio.TimeoutError:
        bars = []
        tags.append("price_fetch_timeout")
    price: dict[str, Any] = {"insufficient_price": True}
    if bars:
        price = extended_price_metrics(bars)
    else:
        tags.append("insufficient_input")

    ann = _announcement_flags(sym)
    if ann.get("tags"):
        tags.extend(ann["tags"])

    news_metrics: dict[str, Any] = {}
    try:
        news_probe = NewsProbe()
        nr = await asyncio.wait_for(news_probe.fetch(sym), timeout=12.0)
        if nr.success:
            news_metrics = nr.data or {}
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("news probe skip %s: %s", sym, exc)
        tags.append("media_sentiment_absent")

    try:
        event_probe = EventProbe()
        await asyncio.wait_for(event_probe.fetch(sym), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        tags.append("event_probe_timeout")

    phys = _phys_probe_active_count(sym)
    if phys == 0:
        tags.append("phys_probe_absent")

    return PhaseSignals(
        symbol=sym,
        name=entry.name or sym,
        pct_chg_1d=price.get("pct_change_1d"),
        pct_chg_3d=price.get("pct_chg_3d"),
        pct_chg_5d=price.get("pct_chg_5d"),
        pct_chg_30d=price.get("pct_chg_30d"),
        pct_chg_60d=price.get("pct_chg_60d"),
        volume_ratio_5d=price.get("volume_ratio_5d"),
        price_below_ma10=price.get("price_below_ma10"),
        media_news_count_7d=int(news_metrics.get("total_count_7d") or 0),
        phys_probe_alerts_active=phys,
        has_q_report_released=bool(ann.get("has_q_report_released")),
        has_pre_announce_released=bool(ann.get("has_pre_announce_released")),
        has_major_contract=bool(ann.get("has_major_contract")),
        no_announcement_positive=bool(ann.get("no_announcement_positive")),
        insufficient_price=bool(price.get("insufficient_price")),
        tags=tags,
    )
