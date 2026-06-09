"""#23 核心内部人实际净减持 · Tushare stk_holdertrade 管道。

[Ref: 28_ §3.2.7]
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.insider_sell_storage import (
    INSIDER_LOOKBACK_CALENDAR_DAYS,
    build_payload_from_pg,
    count_insider_events,
    load_insider_redis,
    mark_insider_backfill_done,
    save_insider_redis,
    trim_t0_payload_for_raw_store,
    upsert_insider_events,
)
from apps.copilot.modules.executing.smart_money_flow import (
    fetch_moneyflow_api,
    symbol_to_ts_code,
    tushare_token,
)

logger = logging.getLogger(__name__)

SOURCE_INSIDER = "Tushare Pro (stk_holdertrade)"
WINDOW_CALENDAR_DAYS = 130
SIGNAL_FADE_DAYS = 30
CLUSTER_NET_SELL_THRESHOLD = 0.01
CLUSTER_SELLERS_THRESHOLD = 3
_INCR_CALENDAR = 90
_FULL_CALENDAR = INSIDER_LOOKBACK_CALENDAR_DAYS


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def _normalize_in_out(raw: str) -> str:
    s = str(raw or "").upper().strip()
    if s in ("OUT", "DE", "D", "SELL", "减持"):
        return "OUT"
    if s in ("IN", "I", "BUY", "增持"):
        return "IN"
    return s


def _vol_to_shares(raw: Any) -> float:
    """Tushare change_vol 字段：实测为大额时为「股」，小值为「万股」。"""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    if v < 100_000:
        return v * 10_000
    return v


def fetch_latest_free_float_shares(symbol: str) -> float | None:
    """最新自由流通股本（股）。"""
    try:
        _, ff, _ = fetch_moneyflow_api(symbol, calendar_lookback=30)
        return float(ff) if ff else None
    except Exception:
        return None


def fetch_insider_trades_api(
    symbol: str,
    *,
    calendar_lookback: int = _INCR_CALENDAR,
) -> list[dict[str, Any]]:
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    pro = _pro_api()
    df = pro.stk_holdertrade(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        in_out = _normalize_in_out(r.get("in_de") or r.get("in_out") or "")
        if in_out not in ("IN", "OUT"):
            continue
        ann = str(r.get("ann_date") or "")
        trade = ann
        if not ann:
            continue
        rows.append(
            {
                "ann_date": ann,
                "trade_date": trade,
                "holder_name": str(r.get("holder_name") or "")[:120],
                "holder_type": str(r.get("holder_type") or "")[:32],
                "in_out": in_out,
                "change_vol_shares": _vol_to_shares(r.get("change_vol")),
            }
        )
    return rows


async def sync_insider_sell_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    cal = _FULL_CALENDAR if mode == "full" else _INCR_CALENDAR
    rows = fetch_insider_trades_api(sym, calendar_lookback=cal)
    n_upsert = await upsert_insider_events(session, sym, rows, source=SOURCE_INSIDER)
    if mode == "full":
        mark_insider_backfill_done(redis_client, sym)
    ff = fetch_latest_free_float_shares(sym)
    pg_count = await count_insider_events(session, sym)
    payload = await build_payload_from_pg(session, sym, free_float_shares=ff)
    payload["ts_code"] = symbol_to_ts_code(sym)
    save_insider_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "api_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "free_float_shares": ff,
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_insider_sell_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    cached = load_insider_redis(redis_client, sym)
    if cached and cached.get("events") is not None:
        if cached.get("free_float_shares"):
            return cached
    ff = fetch_latest_free_float_shares(sym)
    pg_count = await count_insider_events(session, sym)
    if pg_count < 1 and not ff:
        return None
    payload = await build_payload_from_pg(session, sym, free_float_shares=ff)
    save_insider_redis(redis_client, sym, payload)
    return payload


def _resolve_threat_urgency(
    *,
    net_sell: float,
    ratio: float,
    days_since: int | None,
    seller_count: int,
    cluster: bool,
) -> str:
    """T1 威胁紧迫度 · 供 Opus 半衰期降级（不改 90 日 value 统计口径）。"""
    if net_sell <= 0 or seller_count == 0:
        return "NONE"
    if days_since is None:
        return "MODERATE"
    if days_since > SIGNAL_FADE_DAYS:
        return "LOW_FADED"
    if cluster:
        return "HIGH_CLUSTER"
    if days_since <= 7 and ratio >= CLUSTER_NET_SELL_THRESHOLD:
        return "ELEVATED"
    return "MODERATE"


def _build_fact_statement(
    *,
    value_pct: float,
    net_sell: float,
    seller_count: int,
    cluster: bool,
    cluster_note: str,
    days_since: int | None,
    threat_urgency: str,
) -> str:
    base = (
        f"过去 90 个交易日内发生内部人净"
        f"{'抛售' if net_sell >= 0 else '买入'}"
        f"（占盘比 {abs(value_pct):.2f}%）。"
        f"期间共有 {seller_count} 名独立内部人执行了单向卖出动作"
        f"{cluster_note}。"
    )
    if threat_urgency == "LOW_FADED" and days_since is not None:
        return (
            f"{base}[强制降级警报]：但检测到最近一笔抛售发生在 {days_since} 天前"
            f"（>{SIGNAL_FADE_DAYS} 天安全阈值）。"
            "该抛售的盘口物理冲击已严重衰减，大概率已被市场消化（Price-in）。"
            "请勿将上述 90 日窗口统计值等同于当下致命威胁。"
        )
    if threat_urgency == "HIGH_CLUSTER":
        return (
            f"{base}[高紧迫度]：近 {SIGNAL_FADE_DAYS} 日内发生集群卖出，"
            "净抛压与独立卖出人数均达预设逃生阈值。"
        )
    if threat_urgency == "ELEVATED":
        return (
            f"{base}[关注]：最近一笔内部人卖出距今 ≤7 天，"
            "窗口内净抛压仍具当下盘口意义。"
        )
    if threat_urgency == "NONE":
        return "过去 90 个交易日内无内部人净抛售记录（或净买入）。" + cluster_note
    return base


def compute_insider_sell_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """T1 · 90 日净减持当量 + 协同卖出人数（屏蔽绝对金额）。"""
    ff = payload.get("free_float_shares")
    if ff is None or float(ff) <= 0:
        raise ValueError("free_float_shares 缺失")

    free_float = float(ff)
    cutoff = date.today() - timedelta(days=WINDOW_CALENDAR_DAYS)
    events = list(payload.get("events") or [])

    sell_vol = 0.0
    buy_vol = 0.0
    sellers: set[str] = set()
    buyers: set[str] = set()
    latest_sale: date | None = None

    for ev in events:
        td_s = str(ev.get("trade_date") or "")
        if len(td_s) != 8:
            continue
        td = date(int(td_s[:4]), int(td_s[4:6]), int(td_s[6:8]))
        if td < cutoff:
            continue
        vol = float(ev.get("change_vol_shares") or 0)
        name = str(ev.get("holder_name") or "").strip()
        in_out = str(ev.get("in_out") or "").upper()
        if in_out == "OUT":
            sell_vol += vol
            if name:
                sellers.add(name)
            if latest_sale is None or td > latest_sale:
                latest_sale = td
        elif in_out == "IN":
            buy_vol += vol
            if name:
                buyers.add(name)

    net_sell = sell_vol - buy_vol
    ratio = net_sell / free_float
    value_pct = round(ratio * 100, 2)

    days_since = (date.today() - latest_sale).days if latest_sale else None
    latest_str = latest_sale.strftime("%Y-%m-%d") if latest_sale else "—"

    cluster = ratio >= CLUSTER_NET_SELL_THRESHOLD and len(sellers) >= CLUSTER_SELLERS_THRESHOLD
    cluster_note = ""
    if cluster and (days_since is None or days_since <= SIGNAL_FADE_DAYS):
        cluster_note = (
            f"（预设集群逃生阈值为：净抛售 >{CLUSTER_NET_SELL_THRESHOLD * 100:.1f}% "
            f"且独立卖出人数 >={CLUSTER_SELLERS_THRESHOLD} 人 · 已触发）"
        )

    threat_urgency = _resolve_threat_urgency(
        net_sell=net_sell,
        ratio=ratio,
        days_since=days_since,
        seller_count=len(sellers),
        cluster=cluster,
    )

    fact = _build_fact_statement(
        value_pct=value_pct,
        net_sell=net_sell,
        seller_count=len(sellers),
        cluster=cluster,
        cluster_note=cluster_note,
        days_since=days_since,
        threat_urgency=threat_urgency,
    )

    return {
        "indicator_name": "核心内部人90日实际净减持当量",
        "value": value_pct,
        "fact_statement": fact,
        "calculation_logic": "(近90日内部人实际卖出总股数 - 买入总股数) / 自由流通股本",
        "source": SOURCE_INSIDER,
        "raw_metrics": {
            "90d_net_sell_vol": net_sell,
            "net_sell_to_float_ratio": ratio,
            "unique_sellers_count": len(sellers),
            "unique_buyers_count": len(buyers),
            "latest_trade_date": latest_str,
            "days_since_last_sale": days_since,
            "90d_sell_vol": sell_vol,
            "90d_buy_vol": buy_vol,
            "cluster_escape_triggered": cluster,
            "threat_urgency": threat_urgency,
            "signal_fade_days_threshold": SIGNAL_FADE_DAYS,
            "signal_decay_applied": threat_urgency == "LOW_FADED",
        },
    }
