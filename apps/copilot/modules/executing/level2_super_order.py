"""#18 L2 特大单净动能历史分位 · Tushare moneyflow elg_amount 管道。

T0：仅特大单（elg）日聚合 · PG executing_moneyflow_daily（与 #17 共享底库）。
T1：PercentileRank(今日 net_elg_amount, 过去 120 交易日分布)。

[Ref: 28_ §3.2 #18]
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.moneyflow_storage import (
    count_moneyflow_rows,
    load_moneyflow_rows,
    trim_t0_payload_for_raw_store,
)
from apps.copilot.modules.executing.smart_money_flow import (
    FULL_CALENDAR_LOOKBACK,
    INCREMENTAL_CALENDAR_LOOKBACK,
    SOURCE_TUSHARE,
    sync_smart_money_symbol,
    tushare_token,
)

logger = logging.getLogger(__name__)

SOURCE_ELG = "Tushare L2 Moneyflow (elg_amount)"
SUPER_ORDER_MIN_TRADING_DAYS = 120
SUPER_ORDER_LOOKBACK_DAYS = 120
EXTREME_HIGH_PERCENTILE = 95.0
EXTREME_LOW_PERCENTILE = 5.0
_WAN_TO_YUAN = 10_000


def net_elg_amount_yuan(row: dict[str, Any]) -> float:
    """特大单净流入金额（元）· 仅 elg · 禁止混入 lg 及以下。"""
    if row.get("net_elg_amount") is not None:
        return float(row["net_elg_amount"]) * _WAN_TO_YUAN
    buy_wan = float(row.get("buy_elg_amount") or 0)
    sell_wan = float(row.get("sell_elg_amount") or 0)
    return (buy_wan - sell_wan) * _WAN_TO_YUAN


def percentile_rank(value: float, series: list[float]) -> float:
    """含等值中位修正的历史分位（0~100）。"""
    if not series:
        raise ValueError("分位序列不能为空")
    less = sum(1 for x in series if x < value)
    equal = sum(1 for x in series if x == value)
    return round((less + 0.5 * equal) / len(series) * 100, 2)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _fmt_wan_from_yuan(yuan: float) -> str:
    return f"{yuan / _WAN_TO_YUAN:+.2f}"


def trim_elg_t0_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """T0 raw 摘要 · 末 3 日 elg 样本 + PG 行数。"""
    base = trim_t0_payload_for_raw_store(payload)
    rows = list(payload.get("moneyflow_rows") or [])
    elg_tail = []
    for r in rows[-3:]:
        net_yuan = net_elg_amount_yuan(r)
        elg_tail.append(
            {
                "trade_date": r.get("trade_date"),
                "buy_elg_amount_wan": float(r.get("buy_elg_amount") or 0),
                "sell_elg_amount_wan": float(r.get("sell_elg_amount") or 0),
                "net_elg_amount_yuan": net_yuan,
            }
        )
    base["elg_only"] = True
    base["elg_rows_tail"] = elg_tail
    return base


def _rows_missing_elg_amounts(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return True
    tail = rows[-min(5, len(rows)) :]
    return all(
        float(r.get("buy_elg_amount") or 0) == 0 and float(r.get("sell_elg_amount") or 0) == 0
        for r in tail
    )


async def load_level2_super_order_payload(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = SUPER_ORDER_LOOKBACK_DAYS,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    pg_count = await count_moneyflow_rows(session, sym)
    if pg_count < SUPER_ORDER_MIN_TRADING_DAYS:
        return None
    rows = await load_moneyflow_rows(session, sym, limit=limit)
    if len(rows) < SUPER_ORDER_MIN_TRADING_DAYS:
        return None
    if _rows_missing_elg_amounts(rows):
        return None
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "moneyflow_rows": rows,
        "last_update_date": last_date,
        "rows_in_pg": pg_count,
        "history_store": "executing_moneyflow_daily",
        "elg_only": True,
    }


def compute_level2_super_order_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """T1 · 特大单净流入金额在过去 120 交易日中的历史分位。"""
    rows = list(payload.get("moneyflow_rows") or [])
    if len(rows) < SUPER_ORDER_MIN_TRADING_DAYS:
        raise ValueError(
            f"elg 序列不足 {SUPER_ORDER_MIN_TRADING_DAYS} 交易日（实际 {len(rows)}）"
        )

    window = rows[-SUPER_ORDER_LOOKBACK_DAYS:]
    net_series = [net_elg_amount_yuan(r) for r in window]
    current_net = net_series[-1]
    last_row = window[-1]
    buy_yuan = float(last_row.get("buy_elg_amount") or 0) * _WAN_TO_YUAN
    sell_yuan = float(last_row.get("sell_elg_amount") or 0) * _WAN_TO_YUAN

    pct = percentile_rank(current_net, net_series)
    mean_net = sum(net_series) / len(net_series)
    p95 = _quantile(net_series, 0.95)
    p05 = _quantile(net_series, 0.05)

    direction = "净流入" if current_net >= 0 else "净流出"
    abs_wan = _fmt_wan_from_yuan(abs(current_net))
    threshold_note = ""
    if pct >= EXTREME_HIGH_PERCENTILE:
        threshold_note = f"（系统预设极值异动阈值为 >{EXTREME_HIGH_PERCENTILE:.0f}% · 已触发）"
    elif pct <= EXTREME_LOW_PERCENTILE:
        threshold_note = f"（系统预设极值异动阈值为 <{EXTREME_LOW_PERCENTILE:.0f}% · 已触发）"

    fact = (
        f"今日特大单{direction}额为 {_fmt_wan_from_yuan(current_net)} 万元，"
        f"该绝对数值处于过去 {SUPER_ORDER_LOOKBACK_DAYS} 个交易日样本中的 {pct:.1f}% 分位"
        f"{threshold_note}。"
    )

    return {
        "indicator_name": "L2特大单净动能历史分位",
        "value": pct,
        "fact_statement": fact,
        "calculation_logic": (
            f"PercentileRank(今日特大单净额, 过去{SUPER_ORDER_LOOKBACK_DAYS}日特大单净额分布)"
        ),
        "source": SOURCE_ELG,
        "raw_metrics": {
            "current_net_elg_amount": current_net,
            "current_buy_elg_amount": buy_yuan,
            "current_sell_elg_amount": sell_yuan,
            "120d_mean_net_amount": mean_net,
            "120d_p95_threshold": p95,
            "120d_p05_threshold": p05,
            "lookback_window_days": SUPER_ORDER_LOOKBACK_DAYS,
            "last_update_date": payload.get("last_update_date") or last_row.get("trade_date"),
            "history_rows_in_pg": payload.get("rows_in_pg"),
        },
    }


async def sync_level2_super_order_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    """Tushare moneyflow → PG（共享底库）→ T1 分位输入 payload。"""
    sym = symbol.zfill(6)[-6:]
    if not tushare_token():
        raise RuntimeError("TUSHARE_TOKEN 未配置")

    pg_count = await count_moneyflow_rows(session, sym)
    sync_mode = mode
    if pg_count < SUPER_ORDER_MIN_TRADING_DAYS:
        sync_mode = "full"
    else:
        probe_rows = await load_moneyflow_rows(session, sym, limit=5)
        if _rows_missing_elg_amounts(probe_rows):
            sync_mode = "full"

    cal_hint = FULL_CALENDAR_LOOKBACK if sync_mode == "full" else INCREMENTAL_CALENDAR_LOOKBACK
    result = await sync_smart_money_symbol(
        session, sym, redis_client=redis_client, mode=sync_mode
    )
    payload = await load_level2_super_order_payload(session, sym)
    return {
        **result,
        "symbol": sym,
        "sync_mode": sync_mode,
        "calendar_lookback": cal_hint,
        "payload": payload,
        "t0_summary": trim_elg_t0_summary(result.get("payload") or {}) if result.get("payload") else {},
        "pg_count": await count_moneyflow_rows(session, sym),
    }
