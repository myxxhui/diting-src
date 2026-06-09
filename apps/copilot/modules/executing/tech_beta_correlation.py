"""#25 板块 Beta 共振度与解释系数 · Tushare daily + index_daily 管道。

T0：个股与板块指数 pct_chg 对齐落 executing_beta_correlation_daily。
T1：60 日滚动 Pearson ρ、R²、Beta 与当日 Alpha 残差。

[Ref: 28_ §2.2.8]
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.beta_correlation_storage import (
    BETA_LOOKBACK_WINDOW,
    BETA_MIN_TRADING_DAYS,
    BETA_TARGET_TRADING_DAYS,
    build_payload_from_pg,
    count_beta_rows,
    load_beta_redis,
    load_beta_rows,
    save_beta_redis,
    trim_t0_payload_for_raw_store,
    upsert_beta_rows,
)
from apps.copilot.modules.executing.profile import load_profile
from apps.copilot.modules.executing.smart_money_flow import symbol_to_ts_code, tushare_token

logger = logging.getLogger(__name__)

SOURCE_BETA = "Tushare Pro Index/Daily"
INCREMENTAL_CALENDAR_LOOKBACK = 45
FULL_BETA_CALENDAR_LOOKBACK = 280


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def resolve_sector_index(profile: dict[str, Any]) -> tuple[str, str]:
    """从 profile 解析板块基准指数代码（必须预先配置）。"""
    sector = profile.get("sector_index") or {}
    code = (
        profile.get("sector_index_code")
        or sector.get("ts_code")
        or sector.get("code")
    )
    name = (
        profile.get("sector_index_name")
        or sector.get("name")
        or str(code or "")
    )
    if not code:
        raise ValueError("profile 缺少 sector_index_code（板块基准指数映射）")
    return str(code).strip(), str(name).strip()


def _normalize_pct_chg(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return v / 100.0


def fetch_beta_api(
    symbol: str,
    sector_index_code: str,
    *,
    calendar_lookback: int = INCREMENTAL_CALENDAR_LOOKBACK,
) -> tuple[list[dict[str, Any]], str, str]:
    """Tushare daily + index_daily · 按 trade_date 内连接对齐 pct_chg。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    pro = _pro_api()

    sdf = pro.daily(
        ts_code=ts_code,
        start_date=start_s,
        end_date=end_s,
        fields="ts_code,trade_date,pct_chg",
    )
    if sdf is None or sdf.empty:
        raise ValueError(f"daily 无 pct_chg 数据 ts_code={ts_code}")

    idf = pro.index_daily(
        ts_code=sector_index_code,
        start_date=start_s,
        end_date=end_s,
        fields="ts_code,trade_date,pct_chg",
    )
    if idf is None or idf.empty:
        raise ValueError(f"index_daily 无数据 ts_code={sector_index_code}")

    stock_map: dict[str, float] = {}
    for _, r in sdf.iterrows():
        pct = _normalize_pct_chg(r.get("pct_chg"))
        if pct is not None:
            stock_map[str(r.get("trade_date", ""))] = pct

    index_map: dict[str, float] = {}
    for _, r in idf.iterrows():
        pct = _normalize_pct_chg(r.get("pct_chg"))
        if pct is not None:
            index_map[str(r.get("trade_date", ""))] = pct

    common_dates = sorted(set(stock_map) & set(index_map))
    rows: list[dict[str, Any]] = []
    for td in common_dates:
        rows.append(
            {
                "trade_date": td,
                "sector_index_code": sector_index_code,
                "stock_pct_chg": stock_map[td],
                "index_pct_chg": index_map[td],
            }
        )
    if not rows:
        raise ValueError(f"个股与指数无对齐交易日 ts_code={ts_code} index={sector_index_code}")
    return rows, ts_code, sector_index_code


def _rolling_stats(
    stock_rets: list[float],
    index_rets: list[float],
    *,
    window: int = BETA_LOOKBACK_WINDOW,
) -> tuple[float, float, float]:
    if len(stock_rets) < window or len(index_rets) < window:
        raise ValueError(f"对齐收益率不足 {window} 日")
    s = stock_rets[-window:]
    i = index_rets[-window:]
    n = len(s)
    ms = sum(s) / n
    mi = sum(i) / n
    cov = sum((s[j] - ms) * (i[j] - mi) for j in range(n)) / (n - 1)
    vs = sum((s[j] - ms) ** 2 for j in range(n)) / (n - 1)
    vi = sum((i[j] - mi) ** 2 for j in range(n)) / (n - 1)
    if vs <= 0 or vi <= 0:
        raise ValueError("收益率方差为 0，无法计算相关系数")
    pearson_r = cov / (math.sqrt(vs) * math.sqrt(vi))
    r_squared = pearson_r * pearson_r
    beta = cov / vi
    return pearson_r, r_squared, beta


async def sync_tech_beta_correlation_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    prof = profile or load_profile(sym)
    sector_code, sector_name = resolve_sector_index(prof)
    cal = FULL_BETA_CALENDAR_LOOKBACK if mode == "full" else INCREMENTAL_CALENDAR_LOOKBACK
    rows, ts_code, _ = fetch_beta_api(sym, sector_code, calendar_lookback=cal)
    n_upsert = await upsert_beta_rows(session, sym, rows, source=SOURCE_BETA)
    pg_count = await count_beta_rows(session, sym)
    payload = await build_payload_from_pg(
        session,
        sym,
        sector_index_code=sector_code,
        sector_index_name=sector_name,
        limit=max(BETA_TARGET_TRADING_DAYS, pg_count),
    )
    payload["ts_code"] = ts_code
    save_beta_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "api_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "sector_index_code": sector_code,
        "sector_index_name": sector_name,
        "needs_full_backfill": pg_count < BETA_MIN_TRADING_DAYS,
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_tech_beta_correlation_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    prof = profile or load_profile(sym)
    try:
        sector_code, sector_name = resolve_sector_index(prof)
    except ValueError:
        return None

    cached = load_beta_redis(redis_client, sym)
    if cached and len(cached.get("aligned_rows") or []) >= BETA_MIN_TRADING_DAYS:
        return cached

    pg_count = await count_beta_rows(session, sym)
    if pg_count < BETA_MIN_TRADING_DAYS:
        return None
    rows = await load_beta_rows(session, sym, limit=max(BETA_TARGET_TRADING_DAYS, pg_count))
    if len(rows) < BETA_MIN_TRADING_DAYS:
        return None
    payload = await build_payload_from_pg(
        session,
        sym,
        sector_index_code=sector_code,
        sector_index_name=sector_name,
        limit=len(rows),
    )
    save_beta_redis(redis_client, sym, payload)
    return payload


def compute_tech_beta_correlation_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("aligned_rows") or [])
    if len(rows) < BETA_MIN_TRADING_DAYS:
        raise ValueError(
            f"对齐收益率序列不足 {BETA_MIN_TRADING_DAYS} 日（当前 {len(rows)}）"
        )

    stock_rets = [float(r["stock_pct_chg"]) for r in rows]
    index_rets = [float(r["index_pct_chg"]) for r in rows]
    pearson_r, r_squared, beta = _rolling_stats(stock_rets, index_rets)

    today_stock = stock_rets[-1]
    today_index = index_rets[-1]
    alpha_deviation = today_stock - beta * today_index

    sector_code = str(payload.get("sector_index_code") or rows[-1].get("sector_index_code") or "")
    sector_name = str(payload.get("sector_index_name") or sector_code)
    trade_date = str(rows[-1].get("trade_date") or "")
    td_disp = trade_date
    if len(td_disp) == 8:
        td_disp = f"{td_disp[:4]}-{td_disp[4:6]}-{td_disp[6:8]}"

    r_disp = round(pearson_r, 3)
    r2_pct = round(r_squared * 100, 1)
    beta_disp = round(beta, 2)
    value = round(pearson_r, 2)

    fact = (
        f"近 {BETA_LOOKBACK_WINDOW} 个交易日内，该标的与基准板块指数"
        f"（{sector_name}）的滚动相关系数为 {r_disp:.3f}。"
        f"系统测算板块波动解释了该标的约 {r2_pct:.1f}% 的涨跌幅 (R-squared)。"
        f"标的当前弹性 Beta 值为 {beta_disp:.2f}。"
    )

    return {
        "indicator_name": "板块Beta共振度与解释系数",
        "value": value,
        "fact_statement": fact,
        "calculation_logic": (
            f"PearsonCorr(标的近{BETA_LOOKBACK_WINDOW}日收益率, 指数近{BETA_LOOKBACK_WINDOW}日收益率)"
        ),
        "source": SOURCE_BETA,
        "raw_metrics": {
            "lookback_window": BETA_LOOKBACK_WINDOW,
            "pearson_r": r_disp,
            "r_squared": round(r_squared, 3),
            "beta_coefficient": beta_disp,
            "sector_index_used": sector_code,
            "sector_index_name": sector_name,
            "alpha_deviation_today": round(alpha_deviation, 4),
            "trade_date": td_disp[:10],
            "history_rows_in_pg": payload.get("rows_in_pg"),
        },
    }
