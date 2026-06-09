"""#22 户均持股集中度 · AkShare 股东户数快照 + T1 分位/时效性净化。

[Ref: 28_ §3.2.6]
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.retail_concentration_storage import (
    RETAIL_LOOKBACK_QUARTERS,
    RETAIL_MIN_SNAPSHOTS,
    build_payload_from_pg,
    count_retail_snapshots,
    load_retail_redis,
    load_retail_snapshots,
    save_retail_redis,
    trim_t0_payload_for_raw_store,
    upsert_retail_snapshots,
)
from apps.copilot.modules.executing.smart_money_flow import symbol_to_ts_code, tushare_token

logger = logging.getLogger(__name__)

SOURCE_RETAIL = "AkShare Interactive Platform Scraper (Event-Driven)"
STALE_DAYS_THRESHOLD = 30
RETAIL_DANGER_PERCENTILE = 20.0
_WAN_SHARES = 10_000


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def _parse_pct(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if abs(v) > 3:
        return v / 100.0
    return v


def fetch_free_share_map(symbol: str, *, start: date, end: date) -> dict[str, float]:
    """trade_date YYYYMMDD → 自由流通股本(股)。"""
    ts_code = symbol_to_ts_code(symbol)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    try:
        pro = _pro_api()
    except RuntimeError:
        return {}
    basic = pro.daily_basic(
        ts_code=ts_code,
        start_date=start_s,
        end_date=end_s,
        fields="ts_code,trade_date,free_share,float_share",
    )
    out: dict[str, float] = {}
    if basic is None or basic.empty:
        return out
    for _, br in basic.iterrows():
        td = str(br.get("trade_date", ""))
        raw = br.get("free_share")
        if raw is None or float(raw) <= 0:
            raw = br.get("float_share")
        if raw is None or float(raw) <= 0:
            continue
        out[td] = float(raw) * _WAN_SHARES
    return out


def _nearest_free_float(ff_map: dict[str, float], end_date: str) -> float | None:
    if not ff_map:
        return None
    if end_date in ff_map:
        return ff_map[end_date]
    keys = sorted(ff_map.keys())
    prior = [k for k in keys if k <= end_date]
    if prior:
        return ff_map[prior[-1]]
    return ff_map[keys[0]]


def fetch_holder_snapshots_api(symbol: str) -> list[dict[str, Any]]:
    """AkShare stock_zh_a_gdhs_detail_em · 全量股东户数快照。"""
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("akshare 不可用") from exc

    sym = symbol.zfill(6)[-6:]
    df = ak.stock_zh_a_gdhs_detail_em(symbol=sym)
    if df is None or df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        end_raw = r.get("股东户数统计截止日")
        if end_raw is None:
            continue
        end_dt = end_raw if isinstance(end_raw, date) else None
        if end_dt is None:
            try:
                import pandas as pd  # type: ignore

                end_dt = pd.to_datetime(end_raw).date()
            except Exception:
                continue
        end_s = end_dt.strftime("%Y%m%d")

        ann_raw = r.get("股东户数公告日期")
        ann_s = ""
        if ann_raw is not None:
            try:
                import pandas as pd  # type: ignore

                ann_s = pd.to_datetime(ann_raw).strftime("%Y%m%d")
            except Exception:
                ann_s = str(ann_raw)[:10].replace("-", "")

        holder = r.get("股东户数-本次")
        prev = r.get("股东户数-上次")
        chg = r.get("股东户数-增减比例")
        if holder is None:
            continue
        holder_f = float(holder)
        prev_f = float(prev) if prev is not None else None
        chg_f = _parse_pct(chg)
        if chg_f is None and prev_f and prev_f > 0:
            chg_f = (holder_f - prev_f) / prev_f

        rows.append(
            {
                "end_date": end_s,
                "announce_date": ann_s,
                "holder_num": holder_f,
                "previous_holder_num": prev_f,
                "holder_num_change": chg_f,
            }
        )

    rows.sort(key=lambda x: x["end_date"])
    if not rows:
        return rows

    min_end = date(int(rows[0]["end_date"][:4]), int(rows[0]["end_date"][4:6]), int(rows[0]["end_date"][6:8]))
    max_end = date(int(rows[-1]["end_date"][:4]), int(rows[-1]["end_date"][4:6]), int(rows[-1]["end_date"][6:8]))
    ff_map = fetch_free_share_map(sym, start=min_end - timedelta(days=30), end=max_end + timedelta(days=5))

    for row in rows:
        ff = _nearest_free_float(ff_map, row["end_date"])
        row["free_float_shares"] = ff
        if ff and row["holder_num"] > 0:
            row["avg_hold_vol"] = ff / row["holder_num"]
        else:
            row["avg_hold_vol"] = None

    return rows


def percentile_rank(value: float, population: list[float]) -> float:
    if not population:
        return 50.0
    count = sum(1 for x in population if x <= value)
    return round(100.0 * count / len(population), 2)


def percentile_at(population: list[float], pct: float) -> float | None:
    if not population:
        return None
    ordered = sorted(population)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    idx = max(0, min(len(ordered) - 1, idx))
    return ordered[idx]


async def sync_retail_concentration_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    rows = fetch_holder_snapshots_api(sym)
    n_upsert = await upsert_retail_snapshots(session, sym, rows, source=SOURCE_RETAIL)
    pg_count = await count_retail_snapshots(session, sym)
    payload = await build_payload_from_pg(session, sym)
    save_retail_redis(redis_client, sym, payload)
    return {
        "symbol": sym,
        "status": "ok",
        "api_rows": len(rows),
        "upserted": n_upsert,
        "pg_count": pg_count,
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_retail_concentration_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    cached = load_retail_redis(redis_client, sym)
    if cached and cached.get("snapshots") is not None:
        return cached
    pg_count = await count_retail_snapshots(session, sym)
    if pg_count < 1:
        return None
    payload = await build_payload_from_pg(session, sym)
    save_retail_redis(redis_client, sym, payload)
    return payload


def compute_retail_concentration_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """T1 契约 · 户均持股 3 年分位 + 时效性标注。"""
    snaps = list(payload.get("snapshots") or [])
    if len(snaps) < RETAIL_MIN_SNAPSHOTS:
        raise ValueError(f"股东户数快照不足 {len(snaps)}<{RETAIL_MIN_SNAPSHOTS}")

    latest = snaps[-1]
    avg_series = [float(s["avg_hold_vol"]) for s in snaps if s.get("avg_hold_vol")]
    if len(avg_series) < RETAIL_MIN_SNAPSHOTS:
        raise ValueError("户均持股序列不足，缺 free_share 映射")

    lookback = avg_series[-RETAIL_LOOKBACK_QUARTERS:]
    current_avg = float(latest["avg_hold_vol"] or lookback[-1])
    value_pct = percentile_rank(current_avg, lookback)
    p80 = percentile_at(lookback, 80.0)

    end_s = str(latest.get("end_date", ""))
    end_dt = date(int(end_s[:4]), int(end_s[4:6]), int(end_s[6:8]))
    days_since = (date.today() - end_dt).days
    end_disp = f"{end_s[:4]}-{end_s[4:6]}-{end_s[6:8]}"

    stale = days_since > STALE_DAYS_THRESHOLD
    reliability = "STALE" if stale else "HIGH"
    chg = latest.get("holder_num_change")
    chg_pct = float(chg) * 100 if chg is not None else None

    timeliness = f"距今 {days_since} 天"
    if stale:
        timeliness += " · 数据滞后警告"
    else:
        timeliness += " · 数据时效有效"

    chg_text = f"较上期变化 {chg_pct:+.1f}%" if chg_pct is not None else "较上期变化未知"
    if chg_pct is not None and chg_pct > 0:
        chg_text = f"最新披露股东户数较上期激增 {abs(chg_pct):.1f}%"
    elif chg_pct is not None and chg_pct < 0:
        chg_text = f"最新披露股东户数较上期减少 {abs(chg_pct):.1f}%"

    danger = value_pct <= RETAIL_DANGER_PERCENTILE
    fact = (
        f"截至 {end_disp}（{timeliness}），{chg_text}。"
        f"当前户均持股量处于近 {RETAIL_LOOKBACK_QUARTERS} 期历史样本的 {value_pct:.1f}% "
        f"{'极低' if danger else ''}分位"
        f"（预设高危散户化阈值为 <{RETAIL_DANGER_PERCENTILE:.0f}%）。"
    )
    if stale:
        fact += " data_stale_warning：快照超过 30 天，决策权重应下调。"

    raw: dict[str, Any] = {
        "snapshot_end_date": end_disp,
        "days_since_snapshot": days_since,
        "current_holder_num": int(latest.get("holder_num") or 0),
        "previous_holder_num": (
            int(latest["previous_holder_num"]) if latest.get("previous_holder_num") else None
        ),
        "holder_change_rate": float(chg) if chg is not None else None,
        "current_avg_hold_vol": current_avg,
        "3yr_p80_concentration": p80,
        "data_reliability": reliability,
    }
    if stale:
        raw["data_stale_warning"] = True

    return {
        "indicator_name": "户均持股集中度与筹码分散检测",
        "value": value_pct,
        "fact_statement": fact,
        "calculation_logic": "PercentileRank(最新户均持股量, 过去3年户均持股量分布)",
        "source": SOURCE_RETAIL,
        "raw_metrics": raw,
    }
