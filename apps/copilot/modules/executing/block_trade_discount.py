"""#21 大宗交易加权折价与盘口冲击 · Tushare block_trade 管道。

[Ref: 28_ §3.2.5]
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.block_trade_storage import (
    BLOCK_TRADE_LOOKBACK_TRADING_DAYS,
    BLOCK_TRADE_MIN_HISTORY_DAYS,
    build_payload_from_pg,
    count_block_trade_rows,
    load_block_trade_redis,
    load_block_trade_rows,
    save_block_trade_redis,
    trim_t0_payload_for_raw_store,
    upsert_block_trade_rows,
)
from apps.copilot.modules.executing.smart_money_flow import symbol_to_ts_code, tushare_token

logger = logging.getLogger(__name__)

SOURCE_BLOCK = "Tushare Block Trade (VWAP Aggregated)"
IMPACT_SILENT_THRESHOLD = 0.001
IMPACT_MATERIAL_THRESHOLD = 0.01
_WAN_TO_YUAN = 10_000
_INCR_CALENDAR = 60
_FULL_CALENDAR = 1200


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def _aggregate_day(
    trades: list[dict[str, Any]],
    *,
    close: float,
    circ_mv_wan: float,
) -> dict[str, Any] | None:
    if not trades or close <= 0 or circ_mv_wan <= 0:
        return None
    total_vol = sum(float(t["vol"]) for t in trades)
    if total_vol <= 0:
        return None
    vwap = sum(float(t["price"]) * float(t["vol"]) for t in trades) / total_vol
    total_amount_yuan = sum(float(t["amount"]) * _WAN_TO_YUAN for t in trades)
    free_float_mv_yuan = circ_mv_wan * _WAN_TO_YUAN
    vwap_discount = (vwap - close) / close
    impact = total_amount_yuan / free_float_mv_yuan if free_float_mv_yuan > 0 else 0.0
    parties = [
        {"buyer": t.get("buyer"), "seller": t.get("seller"), "vol": t.get("vol"), "amount": t.get("amount")}
        for t in trades
    ]
    return {
        "trade_date": str(trades[0]["trade_date"]),
        "vwap_price": vwap,
        "total_vol_wan": total_vol,
        "total_amount_yuan": total_amount_yuan,
        "trades_count": len(trades),
        "close_price": close,
        "free_float_mv_yuan": free_float_mv_yuan,
        "vwap_discount_rate": vwap_discount,
        "float_impact_ratio": impact,
        "buyers_sellers": parties,
    }


def fetch_block_trade_api(
    symbol: str,
    *,
    calendar_lookback: int = _INCR_CALENDAR,
) -> tuple[list[dict[str, Any]], str]:
    """拉取 block_trade + daily_basic · 按日聚合。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    pro = _pro_api()

    df = pro.block_trade(ts_code=ts_code, start_date=start_s, end_date=end_s)
    basic = pro.daily_basic(
        ts_code=ts_code,
        start_date=start_s,
        end_date=end_s,
        fields="ts_code,trade_date,close,circ_mv",
    )
    basic_map: dict[str, dict[str, float]] = {}
    if basic is not None and not basic.empty:
        for _, br in basic.iterrows():
            td = str(br.get("trade_date", ""))
            basic_map[td] = {
                "close": float(br.get("close") or 0),
                "circ_mv": float(br.get("circ_mv") or 0),
            }

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            td = str(r.get("trade_date", ""))
            by_date[td].append(
                {
                    "trade_date": td,
                    "price": float(r.get("price") or 0),
                    "vol": float(r.get("vol") or 0),
                    "amount": float(r.get("amount") or 0),
                    "buyer": str(r.get("buyer") or "")[:120],
                    "seller": str(r.get("seller") or "")[:120],
                }
            )

    daily_rows: list[dict[str, Any]] = []
    for td in sorted(by_date.keys()):
        bm = basic_map.get(td, {})
        close = float(bm.get("close") or 0)
        circ_mv = float(bm.get("circ_mv") or 0)
        agg = _aggregate_day(by_date[td], close=close, circ_mv_wan=circ_mv)
        if agg:
            daily_rows.append(agg)
    return daily_rows, ts_code


async def sync_block_trade_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    cal = _FULL_CALENDAR if mode == "full" else _INCR_CALENDAR
    rows, ts_code = fetch_block_trade_api(sym, calendar_lookback=cal)
    n_upsert = await upsert_block_trade_rows(session, sym, rows, source=SOURCE_BLOCK)
    pg_count = await count_block_trade_rows(session, sym)
    payload = await build_payload_from_pg(session, sym)
    payload["ts_code"] = ts_code
    payload["lookback_trading_days"] = BLOCK_TRADE_LOOKBACK_TRADING_DAYS
    save_block_trade_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "api_daily_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "needs_full_backfill": pg_count < 1 and mode != "full",
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_block_trade_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    cached = load_block_trade_redis(redis_client, sym)
    if cached and cached.get("block_trade_rows") is not None:
        return cached
    pg_count = await count_block_trade_rows(session, sym)
    if pg_count < 1:
        return None
    payload = await build_payload_from_pg(session, sym)
    save_block_trade_redis(redis_client, sym, payload)
    return payload


def _format_trade_date(td: str) -> str:
    s = str(td or "")
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def describe_block_trade_ui_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    """前端展示态：T1 静默时仍返回可读摘要（不喂 Opus）。"""
    if not payload:
        return {
            "mode": "not_ready",
            "message": "大宗 PG 底库未就绪 · 请等待 l4-block-trade-eod（18:00）或手动触发同步",
        }
    rows = list(payload.get("block_trade_rows") or [])
    if not rows:
        return {
            "mode": "no_events",
            "message": "近 3 年窗口内无大宗成交记录 · 探针待命",
            "rows_in_pg": 0,
        }
    latest = rows[-1]
    if compute_block_trade_discount_metrics(payload) is not None:
        return {"mode": "active"}

    impact = float(latest.get("float_impact_ratio") or 0)
    disc = float(latest.get("vwap_discount_rate") or 0)
    td_disp = _format_trade_date(str(latest.get("trade_date", "")))
    amount = float(latest.get("total_amount_yuan") or 0)
    trades = int(latest.get("trades_count") or 0)

    if impact < IMPACT_SILENT_THRESHOLD:
        msg = (
            f"最新大宗 {td_disp}：加权折价 {disc * 100:+.2f}%，"
            f"成交 {amount / 1e8:.2f} 亿 / {trades} 笔，"
            f"盘口冲击 {impact * 100:.3f}% < 0.1% 阈值 · 已静默（不喂 Opus）"
        )
        reason = "impact_below_threshold"
    else:
        msg = f"最新大宗 {td_disp} · 未达 T1 上报条件"
        reason = "other"

    return {
        "mode": "silent",
        "reason": reason,
        "message": msg,
        "latest_trade_date": td_disp,
        "vwap_discount_rate": disc,
        "float_impact_ratio": impact,
        "total_amount_yuan": amount,
        "trades_count": trades,
        "history_event_days": len(rows),
        "rows_in_pg": payload.get("rows_in_pg", len(rows)),
    }


def compute_block_trade_discount_metrics(payload: dict[str, Any]) -> dict[str, Any] | None:
    """T1 契约 · 冲击 <0.1% 或无成交日返回 None（静默不发 Opus）。"""
    rows = list(payload.get("block_trade_rows") or [])
    if not rows:
        return None

    latest = rows[-1]
    impact = float(latest.get("float_impact_ratio") or 0)
    if impact < IMPACT_SILENT_THRESHOLD:
        return None

    vdr = float(latest.get("vwap_discount_rate") or 0)
    value_pct = round(vdr * 100, 2)
    impact_pct = impact * 100

    hist_rates = [
        float(r["vwap_discount_rate"])
        for r in rows[:-1]
        if r.get("vwap_discount_rate") is not None
    ]
    hist_mean = sum(hist_rates) / len(hist_rates) if hist_rates else vdr

    td = str(latest.get("trade_date", ""))
    if len(td) == 8:
        td_disp = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    else:
        td_disp = td[:10]

    material_note = ""
    if impact >= IMPACT_MATERIAL_THRESHOLD:
        material_note = f"（系统设定的实质性冲击阈值为 >{IMPACT_MATERIAL_THRESHOLD * 100:.1f}% · 已触发）"

    fact = (
        f"{td_disp} 发生大宗交易，量价加权折价率为 {value_pct:.2f}%。"
        f"大宗成交总额占当前自由流通市值的 {impact_pct:.2f}%{material_note}。"
    )

    return {
        "indicator_name": "大宗交易加权折价与盘口冲击",
        "value": value_pct,
        "fact_statement": fact,
        "calculation_logic": "(加权大宗成交均价 - T日收盘价) / T日收盘价",
        "source": SOURCE_BLOCK,
        "raw_metrics": {
            "vwap_discount_rate": vdr,
            "float_impact_ratio": impact,
            "total_block_amount": float(latest.get("total_amount_yuan") or 0),
            "free_float_mv": float(latest.get("free_float_mv_yuan") or 0),
            "historical_mean_discount": hist_mean,
            "trades_count": int(latest.get("trades_count") or 0),
            "trade_date": td_disp,
            "vwap_price": float(latest.get("vwap_price") or 0),
            "close_price": float(latest.get("close_price") or 0),
        },
    }
