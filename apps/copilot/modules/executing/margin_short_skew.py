"""#19 两融杠杆倾斜度历史分位 · Tushare margin_detail 管道（T+1）。

[Ref: 28_ §3.2.3]
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.level2_super_order import percentile_rank
from apps.copilot.modules.executing.margin_storage import (
    MARGIN_MIN_TRADING_DAYS,
    MARGIN_TARGET_TRADING_DAYS,
    build_payload_from_pg,
    count_margin_rows,
    load_margin_redis,
    load_margin_rows,
    save_margin_redis,
    trim_t0_payload_for_raw_store,
    upsert_margin_rows,
)
from apps.copilot.modules.executing.smart_money_flow import symbol_to_ts_code, tushare_token

logger = logging.getLogger(__name__)

SOURCE_MARGIN = "Tushare Margin Detail (T+1 Lag)"
SETTLEMENT_LAG_DAYS = 1
EXTREME_HIGH_PERCENTILE = 95.0
_WAN_SHARES = 10_000
INCREMENTAL_CALENDAR_LOOKBACK = 45
FULL_MARGIN_CALENDAR_LOOKBACK = 400


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def _parse_td(raw: str) -> date:
    s = str(raw).strip().replace("-", "")
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def _margin_short_ratio(rzye: float, rqye: float) -> float | None:
    if rqye <= 0:
        return None
    return rzye / rqye


def _margin_to_float_ratio(rzye: float, free_share_wan: float, close: float) -> float | None:
    if free_share_wan <= 0 or close <= 0 or rzye <= 0:
        return None
    cap = free_share_wan * _WAN_SHARES * close
    if cap <= 0:
        return None
    return rzye / cap


def fetch_margin_api(
    symbol: str,
    *,
    calendar_lookback: int = INCREMENTAL_CALENDAR_LOOKBACK,
) -> tuple[list[dict[str, Any]], str]:
    """Tushare margin_detail + daily_basic 合并 · 衍生杠杆占盘比。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    pro = _pro_api()

    df = pro.margin_detail(ts_code=ts_code, start_date=start_s, end_date=end_s)
    if df is None or df.empty:
        raise ValueError(f"margin_detail 无数据 ts_code={ts_code}")

    basic = pro.daily_basic(
        ts_code=ts_code,
        start_date=start_s,
        end_date=end_s,
        fields="ts_code,trade_date,free_share,close",
    )
    basic_map: dict[str, dict[str, float]] = {}
    if basic is not None and not basic.empty:
        for _, br in basic.iterrows():
            td = str(br.get("trade_date", ""))
            basic_map[td] = {
                "free_share": float(br.get("free_share") or 0),
                "close": float(br.get("close") or 0),
            }

    rows: list[dict[str, Any]] = []
    for _, r in df.sort_values("trade_date", ascending=True).iterrows():
        td = str(r.get("trade_date", ""))
        rzye = float(r.get("rzye") or 0)
        rqye = float(r.get("rqye") or 0)
        rzmre = float(r.get("rzmre") or 0)
        bm = basic_map.get(td, {})
        ff_wan = float(bm.get("free_share") or 0)
        close = float(bm.get("close") or 0)
        cap = ff_wan * _WAN_SHARES * close if ff_wan > 0 and close > 0 else None
        mtf = _margin_to_float_ratio(rzye, ff_wan, close)
        rows.append(
            {
                "trade_date": td,
                "rzye": rzye,
                "rqye": rqye,
                "rzmre": rzmre,
                "margin_short_ratio": _margin_short_ratio(rzye, rqye),
                "free_float_mkt_cap": cap,
                "margin_to_float_ratio": mtf,
            }
        )
    return rows, ts_code


def _enrich_payload_meta(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("margin_rows") or [])
    if not rows:
        return payload
    last_td = _parse_td(rows[-1]["trade_date"])
    lag = (date.today() - last_td).days
    payload["inferred_trade_date"] = last_td.isoformat()
    payload["settlement_lag_days"] = max(lag, 0)
    payload["last_update_date"] = rows[-1]["trade_date"]
    return payload


async def sync_margin_skew_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    cal = FULL_MARGIN_CALENDAR_LOOKBACK if mode == "full" else INCREMENTAL_CALENDAR_LOOKBACK
    rows, ts_code = fetch_margin_api(sym, calendar_lookback=cal)
    n_upsert = await upsert_margin_rows(session, sym, rows, source=SOURCE_MARGIN)
    pg_count = await count_margin_rows(session, sym)
    payload = await build_payload_from_pg(session, sym, limit=MARGIN_TARGET_TRADING_DAYS)
    payload = _enrich_payload_meta(payload)
    payload["ts_code"] = ts_code
    save_margin_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "api_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "needs_full_backfill": pg_count < MARGIN_TARGET_TRADING_DAYS,
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_margin_skew_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    cached = load_margin_redis(redis_client, sym)
    if cached and len(cached.get("margin_rows") or []) >= MARGIN_MIN_TRADING_DAYS:
        valid = [r for r in cached["margin_rows"] if r.get("margin_to_float_ratio") is not None]
        if len(valid) >= MARGIN_MIN_TRADING_DAYS:
            return cached
    pg_count = await count_margin_rows(session, sym)
    if pg_count < MARGIN_MIN_TRADING_DAYS:
        return None
    rows = await load_margin_rows(session, sym, limit=MARGIN_TARGET_TRADING_DAYS)
    valid = [r for r in rows if r.get("margin_to_float_ratio") is not None]
    if len(valid) < MARGIN_MIN_TRADING_DAYS:
        return None
    payload = await build_payload_from_pg(session, sym)
    payload = _enrich_payload_meta(payload)
    save_margin_redis(redis_client, sym, payload)
    return payload


def compute_margin_short_skew_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    rows = [r for r in (payload.get("margin_rows") or []) if r.get("margin_to_float_ratio") is not None]
    if len(rows) < MARGIN_MIN_TRADING_DAYS:
        raise ValueError(f"杠杆占盘比序列不足 {MARGIN_MIN_TRADING_DAYS}（有效 {len(rows)}）")

    window = rows[-MARGIN_TARGET_TRADING_DAYS:]
    ratio_series = [float(r["margin_to_float_ratio"]) for r in window]
    latest = window[-1]
    current_ratio = ratio_series[-1]
    pct = percentile_rank(current_ratio, ratio_series)
    mean_ratio = sum(ratio_series) / len(ratio_series)

    inferred = payload.get("inferred_trade_date") or latest.get("trade_date", "")
    if inferred and len(str(inferred)) == 8:
        inferred = f"{inferred[:4]}-{inferred[4:6]}-{inferred[6:8]}"
    lag = int(payload.get("settlement_lag_days") or SETTLEMENT_LAG_DAYS)
    ratio_pct = round(current_ratio * 100, 2)
    threshold_note = ""
    if pct >= EXTREME_HIGH_PERCENTILE:
        threshold_note = f"（系统预设高危杠杆堰塞湖阈值为 >{EXTREME_HIGH_PERCENTILE:.0f}% · 已触发）"

    fact = (
        f"截至 T-{lag} 日（数据交易日 {inferred}），该标的融资余额占流通盘比例升至 {ratio_pct:.2f}%，"
        f"此杠杆倾斜度处于过去 {MARGIN_TARGET_TRADING_DAYS} 个交易日样本中的 {pct:.1f}% 分位"
        f"{threshold_note}。"
    )

    return {
        "indicator_name": "两融杠杆倾斜度历史分位",
        "value": pct,
        "fact_statement": fact,
        "calculation_logic": (
            f"PercentileRank(今日融资余额/流通市值, 过去{MARGIN_TARGET_TRADING_DAYS}日同维度分布)"
        ),
        "source": SOURCE_MARGIN,
        "raw_metrics": {
            "inferred_trade_date": str(inferred)[:10],
            "margin_balance": float(latest.get("rzye") or 0),
            "short_balance": float(latest.get("rqye") or 0),
            "margin_purchase_today": float(latest.get("rzmre") or 0),
            "margin_to_float_ratio": current_ratio,
            "250d_mean_ratio": mean_ratio,
            "settlement_lag_days": lag,
            "lookback_window_days": MARGIN_TARGET_TRADING_DAYS,
            "history_rows_in_pg": payload.get("rows_in_pg"),
        },
    }
