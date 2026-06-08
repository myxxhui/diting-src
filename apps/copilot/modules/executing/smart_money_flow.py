"""L2 主力大单资金流向 · Tushare moneyflow 管道（250 日 PG + Redis）。

T0：moneyflow 日终聚合落 executing_moneyflow_daily · Redis 热缓存。
T1：阶级隔离（elg+lg）→ 3 日累计 → 流通盘归一化（Smart Money Delta）。

[Ref: 28_ §3.2.1 #17]
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.moneyflow_storage import (
    MONEYFLOW_MIN_TRADING_DAYS,
    MONEYFLOW_TARGET_TRADING_DAYS,
    build_payload_from_pg,
    count_moneyflow_rows,
    load_moneyflow_redis,
    load_moneyflow_rows,
    save_moneyflow_redis,
    trim_t0_payload_for_raw_store,
    upsert_moneyflow_rows,
)

logger = logging.getLogger(__name__)

_LOT_SIZE = 100
_WAN_SHARES = 10_000
SOURCE_TUSHARE = "Tushare API (moneyflow)"
FULL_CALENDAR_LOOKBACK = 400
INCREMENTAL_CALENDAR_LOOKBACK = 14


def tushare_token() -> str | None:
    tok = (os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_PRO_TOKEN") or "").strip()
    return tok or None


def symbol_to_ts_code(symbol: str) -> str:
    sym = symbol.zfill(6)[-6:]
    suffix = "SH" if sym.startswith(("5", "6", "9")) else "SZ"
    return f"{sym}.{suffix}"


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def _row_from_df(r: Any) -> dict[str, Any]:
    return {
        "trade_date": str(r.get("trade_date", "")),
        "buy_elg_vol": float(r.get("buy_elg_vol") or 0),
        "sell_elg_vol": float(r.get("sell_elg_vol") or 0),
        "buy_lg_vol": float(r.get("buy_lg_vol") or 0),
        "sell_lg_vol": float(r.get("sell_lg_vol") or 0),
        "buy_md_vol": float(r.get("buy_md_vol") or 0),
        "sell_md_vol": float(r.get("sell_md_vol") or 0),
        "buy_sm_vol": float(r.get("buy_sm_vol") or 0),
        "sell_sm_vol": float(r.get("sell_sm_vol") or 0),
        "net_mf_vol": float(r.get("net_mf_vol") or 0),
    }


def fetch_moneyflow_api(
    symbol: str,
    *,
    calendar_lookback: int = INCREMENTAL_CALENDAR_LOOKBACK,
) -> tuple[list[dict[str, Any]], float | None, str]:
    """从 Tushare 拉 moneyflow 行 + 最新自由流通股本。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    pro = _pro_api()
    df = pro.moneyflow(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        raise ValueError(f"moneyflow 无数据 ts_code={ts_code}")

    basic = pro.daily_basic(
        ts_code=ts_code,
        start_date=(end - timedelta(days=10)).strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        fields="ts_code,trade_date,free_share,float_share",
    )
    free_float_shares: float | None = None
    if basic is not None and not basic.empty:
        basic = basic.sort_values("trade_date", ascending=False)
        row = basic.iloc[0]
        raw_ff = row.get("free_share")
        if raw_ff is not None and float(raw_ff) > 0:
            free_float_shares = float(raw_ff) * _WAN_SHARES
        else:
            raw_fl = row.get("float_share")
            if raw_fl is not None and float(raw_fl) > 0:
                free_float_shares = float(raw_fl) * _WAN_SHARES

    rows: list[dict[str, Any]] = []
    for _, r in df.sort_values("trade_date", ascending=True).iterrows():
        rows.append(_row_from_df(r))
    return rows, free_float_shares, ts_code


def fetch_moneyflow_raw(symbol: str, *, lookback_days: int = INCREMENTAL_CALENDAR_LOOKBACK) -> dict[str, Any]:
    """兼容旧接口：近 N 自然日 API 拉取（不落 PG）。"""
    rows, free_float, ts_code = fetch_moneyflow_api(symbol, calendar_lookback=lookback_days)
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "moneyflow_rows": rows,
        "free_float_shares": free_float,
        "last_update_date": last_date,
        "ts_code": ts_code,
        "rows_in_pg": len(rows),
        "history_store": "api_only",
    }


async def sync_smart_money_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    """同步单标的 moneyflow：PG 底库 + Redis + 返回 T1 可用 payload。"""
    sym = symbol.zfill(6)[-6:]
    cal_days = FULL_CALENDAR_LOOKBACK if mode == "full" else INCREMENTAL_CALENDAR_LOOKBACK
    rows, free_float, ts_code = fetch_moneyflow_api(sym, calendar_lookback=cal_days)
    n_upsert = await upsert_moneyflow_rows(session, sym, rows, source=SOURCE_TUSHARE)
    pg_count = await count_moneyflow_rows(session, sym)
    pg_rows = await load_moneyflow_rows(session, sym, limit=MONEYFLOW_TARGET_TRADING_DAYS)
    payload = await build_payload_from_pg(
        session,
        sym,
        free_float_shares=free_float,
        ts_code=ts_code,
        limit=MONEYFLOW_TARGET_TRADING_DAYS,
    )
    save_moneyflow_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "api_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "pg_rows_loaded": len(pg_rows),
        "target_trading_days": MONEYFLOW_TARGET_TRADING_DAYS,
        "needs_full_backfill": pg_count < MONEYFLOW_TARGET_TRADING_DAYS,
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_smart_money_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    """Redis → PG 回灌 → 组装 T1 输入 payload。"""
    sym = symbol.zfill(6)[-6:]
    cached = load_moneyflow_redis(redis_client, sym)
    if cached and len(cached.get("moneyflow_rows") or []) >= MONEYFLOW_MIN_TRADING_DAYS:
        return cached
    pg_count = await count_moneyflow_rows(session, sym)
    if pg_count < MONEYFLOW_MIN_TRADING_DAYS:
        return None
    ts_code = symbol_to_ts_code(sym)
    payload = await build_payload_from_pg(
        session,
        sym,
        free_float_shares=(cached or {}).get("free_float_shares"),
        ts_code=ts_code,
    )
    if payload.get("free_float_shares") is None and cached:
        payload["free_float_shares"] = cached.get("free_float_shares")
    save_moneyflow_redis(redis_client, sym, payload)
    return payload


def _smart_net_lots(row: dict[str, Any]) -> float:
    buy = float(row.get("buy_elg_vol") or 0) + float(row.get("buy_lg_vol") or 0)
    sell = float(row.get("sell_elg_vol") or 0) + float(row.get("sell_lg_vol") or 0)
    return buy - sell


def _retail_net_lots(row: dict[str, Any]) -> float:
    buy = float(row.get("buy_md_vol") or 0) + float(row.get("buy_sm_vol") or 0)
    sell = float(row.get("sell_md_vol") or 0) + float(row.get("sell_sm_vol") or 0)
    return buy - sell


def compute_smart_money_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """T1 Smart Money Delta · 三步：阶级隔离 → 3 日累计 → 流通盘归一化。"""
    rows = list(payload.get("moneyflow_rows") or [])
    if len(rows) < MONEYFLOW_MIN_TRADING_DAYS:
        raise ValueError(f"moneyflow 行数不足 {MONEYFLOW_MIN_TRADING_DAYS}（实际 {len(rows)}）")

    tail = rows[-3:]
    smart_net_lots = sum(_smart_net_lots(r) for r in tail)
    retail_net_lots = sum(_retail_net_lots(r) for r in tail)
    smart_net_shares = smart_net_lots * _LOT_SIZE
    retail_net_shares = retail_net_lots * _LOT_SIZE

    free_float = payload.get("free_float_shares")
    if free_float is None or float(free_float) <= 0:
        raise ValueError("自由流通股本缺失或无效")

    free_float_f = float(free_float)
    value_pct = round(smart_net_shares / free_float_f * 100, 2)
    direction = "净流入" if value_pct >= 0 else "净流出"
    abs_pct = abs(value_pct)
    last_date = payload.get("last_update_date") or tail[-1].get("trade_date", "")

    return {
        "indicator_name": "L2主力大单资金流向",
        "value_pct": value_pct,
        "calculation_logic": "Sum(近3日大单+特大单净买入量) / 自由流通股本",
        "fact_statement": (
            f"近 3 个交易日内，大单与特大单（主力资金）累计{direction}"
            f"占自由流通盘的 {abs_pct:.2f}%。"
        ),
        "raw_metrics": {
            "3d_smart_money_net_vol": smart_net_shares,
            "3d_retail_net_vol": retail_net_shares,
            "free_float_shares": free_float_f,
            "last_update_date": last_date,
            "history_rows_in_pg": payload.get("rows_in_pg"),
            "tail_trade_dates": [r.get("trade_date") for r in tail],
        },
    }
