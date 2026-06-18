"""#20 自由换手率异动倍数 · Tushare daily_basic 管道。

[Ref: 28_ §3.2.4]
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.level2_super_order import percentile_rank
from apps.copilot.modules.executing.smart_money_flow import symbol_to_ts_code, tushare_token
from apps.copilot.modules.executing.turnover_storage import (
    TURNOVER_BASELINE_DAYS,
    TURNOVER_MIN_TRADING_DAYS,
    TURNOVER_PERCENTILE_WINDOW,
    TURNOVER_TARGET_TRADING_DAYS,
    build_payload_from_pg,
    count_turnover_rows,
    load_turnover_redis,
    load_turnover_rows,
    save_turnover_redis,
    trim_t0_payload_for_raw_store,
    upsert_turnover_rows,
)

logger = logging.getLogger(__name__)

SOURCE_TURNOVER = "Tushare Daily Basic (turnover_rate_f)"
ACCEL_ANOMALY_THRESHOLD = 3.0
INCREMENTAL_CALENDAR_LOOKBACK = 45
FULL_TURNOVER_CALENDAR_LOOKBACK = 280


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def _normalize_turnover_rate(raw: Any) -> float | None:
    """Tushare turnover_rate_f 单位为 %，落库为小数（0.1625 = 16.25%）。NaN/非正数 → None。"""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or v <= 0:
        return None
    return v / 100.0


def fetch_turnover_api(
    symbol: str,
    *,
    calendar_lookback: int = INCREMENTAL_CALENDAR_LOOKBACK,
) -> tuple[list[dict[str, Any]], str]:
    """Tushare daily_basic · 仅 turnover_rate_f + volume_ratio。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    pro = _pro_api()
    df = pro.daily_basic(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        fields="ts_code,trade_date,turnover_rate_f,volume_ratio",
    )
    if df is None or df.empty:
        raise ValueError(f"daily_basic 无 turnover 数据 ts_code={ts_code}")

    rows: list[dict[str, Any]] = []
    for _, r in df.sort_values("trade_date", ascending=True).iterrows():
        rate = _normalize_turnover_rate(r.get("turnover_rate_f"))
        if rate is None:
            continue
        vr = r.get("volume_ratio")
        rows.append(
            {
                "trade_date": str(r.get("trade_date", "")),
                "turnover_rate_f": rate,
                "volume_ratio": float(vr) if vr is not None and str(vr) not in ("", "nan") else None,
            }
        )
    if not rows:
        raise ValueError(f"turnover_rate_f 有效行数为 0 ts_code={ts_code}")
    return rows, ts_code


def _accel_series(
    rows: list[dict[str, Any]],
    *,
    baseline_days: int = TURNOVER_BASELINE_DAYS,
) -> list[tuple[str, float]]:
    series: list[tuple[str, float]] = []
    for i in range(baseline_days, len(rows)):
        window = rows[i - baseline_days : i]
        rates = [float(w["turnover_rate_f"]) for w in window if w.get("turnover_rate_f") is not None]
        if len(rates) < baseline_days:
            continue
        mean = sum(rates) / len(rates)
        if mean <= 0:
            continue
        today = rows[i].get("turnover_rate_f")
        if today is None:
            continue
        series.append((str(rows[i]["trade_date"]), float(today) / mean))
    return series


async def sync_turnover_acceleration_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    cal = FULL_TURNOVER_CALENDAR_LOOKBACK if mode == "full" else INCREMENTAL_CALENDAR_LOOKBACK
    rows, ts_code = fetch_turnover_api(sym, calendar_lookback=cal)
    n_upsert = await upsert_turnover_rows(session, sym, rows, source=SOURCE_TURNOVER)
    pg_count = await count_turnover_rows(session, sym)
    payload = await build_payload_from_pg(session, sym, limit=max(TURNOVER_TARGET_TRADING_DAYS, pg_count))
    payload["ts_code"] = ts_code
    save_turnover_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "api_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "needs_full_backfill": pg_count < TURNOVER_MIN_TRADING_DAYS + TURNOVER_BASELINE_DAYS,
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_turnover_acceleration_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    cached = load_turnover_redis(redis_client, sym)
    if cached and len(cached.get("turnover_rows") or []) >= TURNOVER_MIN_TRADING_DAYS:
        return cached
    pg_count = await count_turnover_rows(session, sym)
    if pg_count < TURNOVER_MIN_TRADING_DAYS:
        return None
    rows = await load_turnover_rows(session, sym, limit=max(TURNOVER_TARGET_TRADING_DAYS, pg_count))
    if len(rows) < TURNOVER_MIN_TRADING_DAYS:
        return None
    payload = await build_payload_from_pg(session, sym, limit=len(rows))
    save_turnover_redis(redis_client, sym, payload)
    return payload


def compute_turnover_acceleration_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("turnover_rows") or [])
    # 剔除 NaN/None 换手率行（Tushare 当日偶尔返回 NaN）
    clean_rows = [r for r in rows if r.get("turnover_rate_f") is not None and not (
        isinstance(r.get("turnover_rate_f"), float) and math.isnan(r["turnover_rate_f"]))]
    if len(clean_rows) < TURNOVER_MIN_TRADING_DAYS + TURNOVER_BASELINE_DAYS:
        raise ValueError(
            f"有效换手率序列不足 {TURNOVER_MIN_TRADING_DAYS + TURNOVER_BASELINE_DAYS}"
            f"（原始 {len(rows)} 行 · 清洗后 {len(clean_rows)} 行）"
        )

    accel = _accel_series(clean_rows)
    if len(accel) < TURNOVER_BASELINE_DAYS:
        raise ValueError(f"加速倍数序列不足（有效 {len(accel)}）")

    window = accel[-TURNOVER_PERCENTILE_WINDOW:]
    trade_date, today_accel = accel[-1]
    pct = percentile_rank(today_accel, [a for _, a in window])

    prior = clean_rows[-(TURNOVER_BASELINE_DAYS + 1) : -1]
    mean20 = sum(float(r["turnover_rate_f"]) for r in prior) / len(prior)
    current = float(clean_rows[-1]["turnover_rate_f"])
    volume_ratio = clean_rows[-1].get("volume_ratio")

    cur_pct = current * 100
    mean_pct = mean20 * 100
    threshold_note = ""
    if today_accel >= ACCEL_ANOMALY_THRESHOLD:
        threshold_note = f"（系统预设异动阈值为 >{ACCEL_ANOMALY_THRESHOLD:.1f} 倍 · 已触发）"

    td_disp = trade_date
    if len(str(td_disp)) == 8:
        td_disp = f"{td_disp[:4]}-{td_disp[4:6]}-{td_disp[6:8]}"

    fact = (
        f"今日（{td_disp}）自由流通换手率为 {cur_pct:.2f}%，"
        f"是其过去 {TURNOVER_BASELINE_DAYS} 个交易日平均换手基线 ({mean_pct:.2f}%) 的 {today_accel:.2f} 倍。"
        f"此加速倍数处于近 {len(window)} 日的 {pct:.1f}% 分位{threshold_note}。"
    )

    return {
        "indicator_name": "自由换手率异动倍数",
        "value": round(today_accel, 2),
        "fact_statement": fact,
        "calculation_logic": (
            f"今日 turnover_rate_f / 过去{TURNOVER_BASELINE_DAYS}日平均 turnover_rate_f"
        ),
        "source": SOURCE_TURNOVER,
        "raw_metrics": {
            "current_turnover_f": current,
            "20d_mean_turnover_f": mean20,
            "120d_accel_percentile": round(pct, 1),
            "volume_ratio": volume_ratio,
            "trade_date": str(td_disp)[:10],
            "lookback_window_days": len(window),
            "history_rows_in_pg": payload.get("rows_in_pg"),
        },
    }
