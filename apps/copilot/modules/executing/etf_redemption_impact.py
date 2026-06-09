"""#24 ETF 被动资金冲击当量 · Tushare fund_portfolio + fund_share 穿透管道。

[Ref: 28_ §3.2.8]
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.etf_redemption_storage import (
    ETF_LOOKBACK_CALENDAR_DAYS,
    build_payload_from_pg,
    count_etf_links,
    get_disc_cursor,
    load_etf_links,
    load_etf_redis,
    load_etf_universe,
    mark_etf_backfill_done,
    save_etf_redis,
    save_etf_universe,
    set_disc_cursor,
    trim_t0_payload_for_raw_store,
    upsert_etf_links,
    upsert_etf_share_rows,
)
from apps.copilot.modules.executing.smart_money_flow import symbol_to_ts_code, tushare_token

logger = logging.getLogger(__name__)

SOURCE_ETF = "Tushare Pro Fund Share & Portfolio (T+1 Lag)"
IMPACT_SILENT_THRESHOLD = 0.01
IMPACT_MATERIAL_THRESHOLD = 0.03
MIN_STOCK_WEIGHT = 0.005
_PORTFOLIO_DISC_BATCH = 12
_WAN_SHARES = 10_000
_AMOUNT_QIAN = 1000
_INCR_CALENDAR = 90
_FULL_CALENDAR = ETF_LOOKBACK_CALENDAR_DAYS

# 指数 → 主被动 ETF 映射（index_weight 快速穿透 · 避免 fund_portfolio 全量扫描）
INDEX_ETF_MAP: dict[str, str] = {
    "000300.SH": "510300.SH",
    "000905.SH": "510500.SH",
    "399006.SZ": "159915.SZ",
    "000852.SH": "512100.SH",
    "000016.SH": "510050.SH",
    "000688.SH": "588000.SH",
    "399303.SZ": "159949.SZ",
    "000932.SH": "512480.SH",
}


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def fetch_etf_universe_api() -> list[str]:
    """上市 ETF 列表 · fund_basic(market=E)。"""
    pro = _pro_api()
    df = pro.fund_basic(market="E", status="L")
    if df is None or df.empty:
        return []
    codes = [str(c).strip() for c in df["ts_code"].tolist() if c]
    return sorted(set(codes))


def discover_links_via_index(symbol: str) -> list[dict[str, Any]]:
    """index_weight 穿透 · 7~8 次 API 即可完成核心指数 ETF 链接。"""
    stock_ts = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=120)
    pro = _pro_api()
    links: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index_code, etf_code in INDEX_ETF_MAP.items():
        try:
            df = pro.index_weight(
                index_code=index_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.warning("index_weight %s failed: %s", index_code, exc)
            continue
        if df is None or df.empty:
            continue
        hit = df[df["con_code"].astype(str) == stock_ts]
        if hit.empty:
            continue
        latest = hit.sort_values("trade_date").iloc[-1]
        w_pct = float(latest.get("weight") or 0)
        w = w_pct / 100.0
        if w < MIN_STOCK_WEIGHT:
            continue
        if etf_code in seen:
            continue
        seen.add(etf_code)
        td = str(latest.get("trade_date") or "")
        links.append(
            {
                "etf_ts_code": etf_code,
                "stock_weight": w,
                "report_end_date": td,
                "link_source": f"index_weight:{index_code}",
            }
        )
    return links


def discover_links_via_portfolio_batch(
    symbol: str,
    etf_universe: list[str],
    *,
    cursor: int,
    batch_size: int = _PORTFOLIO_DISC_BATCH,
) -> tuple[list[dict[str, Any]], int]:
    """fund_portfolio 增量扫描 · 每批 batch_size 只 ETF。"""
    stock_ts = symbol_to_ts_code(symbol)
    sym6 = symbol.zfill(6)[-6:]
    pro = _pro_api()
    links: list[dict[str, Any]] = []
    end = min(cursor + batch_size, len(etf_universe))
    for i in range(cursor, end):
        etf = etf_universe[i]
        try:
            df = pro.fund_portfolio(ts_code=etf)
            time.sleep(0.25)
        except Exception as exc:
            logger.warning("fund_portfolio %s failed: %s", etf, exc)
            time.sleep(1.0)
            continue
        if df is None or df.empty:
            continue
        latest_end = str(df["end_date"].max())
        sub = df[df["end_date"].astype(str) == latest_end]
        hit = sub[sub["symbol"].astype(str) == stock_ts]
        if hit.empty:
            hit = sub[
                sub["symbol"]
                .astype(str)
                .str.replace(".SZ", "", regex=False)
                .str.replace(".SH", "", regex=False)
                .str.zfill(6)
                == sym6
            ]
        if hit.empty:
            continue
        row = hit.iloc[0]
        w_pct = float(row.get("stk_mkv_ratio") or 0)
        w = w_pct / 100.0
        if w < MIN_STOCK_WEIGHT:
            continue
        links.append(
            {
                "etf_ts_code": etf,
                "stock_weight": w,
                "report_end_date": latest_end,
                "link_source": "fund_portfolio",
            }
        )
    next_cursor = end if end < len(etf_universe) else 0
    return links, next_cursor


def fetch_etf_share_nav_api(
    etf_ts_code: str,
    *,
    calendar_lookback: int = _INCR_CALENDAR,
) -> list[dict[str, Any]]:
    """fund_share + fund_nav 对齐 · 计算 fd_share_change。"""
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    pro = _pro_api()

    share_df = pro.fund_share(ts_code=etf_ts_code, start_date=start_s, end_date=end_s)
    nav_df = pro.fund_nav(ts_code=etf_ts_code, start_date=start_s, end_date=end_s)
    if share_df is None or share_df.empty:
        return []

    nav_map: dict[str, float] = {}
    if nav_df is not None and not nav_df.empty:
        for _, nr in nav_df.iterrows():
            nd = str(nr.get("nav_date") or nr.get("trade_date") or "")
            nav = nr.get("unit_nav")
            if nd and nav is not None:
                nav_map[nd] = float(nav)

    rows: list[dict[str, Any]] = []
    prev_share: float | None = None
    for _, sr in share_df.sort_values("trade_date").iterrows():
        td = str(sr.get("trade_date") or "")
        fd = float(sr.get("fd_share") or 0)
        chg = None if prev_share is None else fd - prev_share
        prev_share = fd
        rows.append(
            {
                "trade_date": td,
                "fd_share": fd,
                "fd_share_change": chg,
                "unit_nav": nav_map.get(td),
            }
        )
    return rows


def fetch_stock_daily_amount_api(
    symbol: str,
    *,
    calendar_lookback: int = _INCR_CALENDAR,
) -> dict[str, float]:
    """daily.amount 千元 → 元。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=calendar_lookback)
    pro = _pro_api()
    df = pro.daily(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        fields="ts_code,trade_date,amount",
    )
    out: dict[str, float] = {}
    if df is None or df.empty:
        return out
    for _, r in df.iterrows():
        td = str(r.get("trade_date") or "")
        amt = r.get("amount")
        if td and amt is not None:
            out[td] = float(amt) * _AMOUNT_QIAN
    return out


async def refresh_etf_links(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    source: str = SOURCE_ETF,
) -> int:
    """指数穿透 + fund_portfolio 增量补充。"""
    sym = symbol.zfill(6)[-6:]
    existing = await load_etf_links(session, sym)
    merged: dict[str, dict[str, Any]] = {lk["etf_ts_code"]: lk for lk in existing}

    for lk in discover_links_via_index(sym):
        prev = merged.get(lk["etf_ts_code"])
        if prev is None or lk["stock_weight"] > prev["stock_weight"]:
            merged[lk["etf_ts_code"]] = lk

    universe = load_etf_universe(redis_client)
    if universe is None:
        universe = fetch_etf_universe_api()
        save_etf_universe(redis_client, universe)

    if universe:
        cursor = get_disc_cursor(redis_client, sym)
        batch_links, next_cursor = discover_links_via_portfolio_batch(
            sym, universe, cursor=cursor, batch_size=_PORTFOLIO_DISC_BATCH
        )
        set_disc_cursor(redis_client, sym, next_cursor)
        for lk in batch_links:
            prev = merged.get(lk["etf_ts_code"])
            if prev is None or lk["stock_weight"] > prev["stock_weight"]:
                merged[lk["etf_ts_code"]] = lk

    links = list(merged.values())
    return await upsert_etf_links(session, sym, links, source=source)


async def sync_etf_redemption_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    mode: str = "incremental",
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    cal = _FULL_CALENDAR if mode == "full" else _INCR_CALENDAR

    await refresh_etf_links(session, sym, redis_client=redis_client)
    links = await load_etf_links(session, sym)
    share_upserts = 0
    for lk in links:
        rows = fetch_etf_share_nav_api(lk["etf_ts_code"], calendar_lookback=cal)
        share_upserts += await upsert_etf_share_rows(
            session, lk["etf_ts_code"], rows, source=SOURCE_ETF
        )

    amounts = fetch_stock_daily_amount_api(sym, calendar_lookback=cal)
    if mode == "full":
        mark_etf_backfill_done(redis_client, sym)

    payload = await build_payload_from_pg(session, sym, stock_amount_by_date=amounts)
    payload["ts_code"] = symbol_to_ts_code(sym)
    save_etf_redis(redis_client, sym, payload)

    return {
        "symbol": sym,
        "status": "ok",
        "mode": mode,
        "links_count": len(links),
        "share_upserts": share_upserts,
        "pg_links": await count_etf_links(session, sym),
        "payload": payload,
        "t0_summary": trim_t0_payload_for_raw_store(payload),
    }


async def load_etf_redemption_payload(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    cached = load_etf_redis(redis_client, sym)
    if cached and cached.get("etf_links") is not None:
        return cached
    if await count_etf_links(session, sym) < 1:
        return None
    amounts = fetch_stock_daily_amount_api(sym, calendar_lookback=_INCR_CALENDAR)
    payload = await build_payload_from_pg(session, sym, stock_amount_by_date=amounts)
    save_etf_redis(redis_client, sym, payload)
    return payload


def _resolve_threat_urgency(abs_impact: float) -> str:
    if abs_impact >= IMPACT_MATERIAL_THRESHOLD:
        return "ELEVATED"
    if abs_impact >= IMPACT_SILENT_THRESHOLD:
        return "MODERATE"
    return "NONE"


def compute_etf_redemption_metrics(payload: dict[str, Any]) -> dict[str, Any] | None:
    """T1 · 穿透当量化 · |冲击|<1% 静默。"""
    links = list(payload.get("etf_links") or [])
    if not links:
        return None

    share_series: dict[str, list[dict[str, Any]]] = payload.get("etf_share_series") or {}
    amounts: dict[str, float] = payload.get("stock_amount_by_date") or {}

    # 取各 ETF 最新可算交易日
    latest_td: str | None = None
    for lk in links:
        etf = lk["etf_ts_code"]
        rows = share_series.get(etf) or []
        if not rows:
            continue
        td = str(rows[-1].get("trade_date") or "")
        if td and (latest_td is None or td > latest_td):
            latest_td = td
    if not latest_td:
        return None

    total_passive_sell = 0.0
    etf_contribs: list[dict[str, Any]] = []
    top_etf = ""
    top_weight = 0.0
    top_sell = 0.0

    for lk in links:
        etf = lk["etf_ts_code"]
        weight = float(lk.get("stock_weight") or 0)
        rows = share_series.get(etf) or []
        row = next((r for r in rows if str(r.get("trade_date")) == latest_td), None)
        if not row:
            continue
        chg = row.get("fd_share_change")
        nav = row.get("unit_nav")
        if chg is None or nav is None:
            continue
        chg_f = float(chg)
        nav_f = float(nav)
        if chg_f >= 0:
            continue
        # 净赎回份额(万份) × 1万 × 净值 × 标的权重
        redemption_yuan = abs(chg_f) * _WAN_SHARES * nav_f
        passive = redemption_yuan * weight
        total_passive_sell += passive
        etf_contribs.append(
            {
                "etf_ts_code": etf,
                "etf_net_share_change": chg_f,
                "etf_nav": nav_f,
                "stock_weight_in_etf": weight,
                "implied_passive_sell_amount": passive,
            }
        )
        if passive > top_sell:
            top_sell = passive
            top_etf = etf
            top_weight = weight

    if total_passive_sell <= 0:
        return None

    stock_amount = amounts.get(latest_td)
    if stock_amount is None or stock_amount <= 0:
        # 回退上一交易日成交额
        prior = sorted([k for k in amounts if k < latest_td])
        stock_amount = amounts[prior[-1]] if prior else None
    if stock_amount is None or stock_amount <= 0:
        raise ValueError("stock_daily_amount_base 缺失")

    impact_ratio = -total_passive_sell / float(stock_amount)
    if abs(impact_ratio) < IMPACT_SILENT_THRESHOLD:
        return None

    value_pct = round(impact_ratio * 100, 2)
    td_disp = (
        f"{latest_td[:4]}-{latest_td[4:6]}-{latest_td[6:8]}"
        if len(latest_td) == 8
        else latest_td
    )
    urgency = _resolve_threat_urgency(abs(impact_ratio))
    etf_label = top_etf or (etf_contribs[0]["etf_ts_code"] if etf_contribs else "—")

    material_note = ""
    if abs(impact_ratio) >= IMPACT_MATERIAL_THRESHOLD:
        material_note = (
            f"（系统预设实质性冲击阈值为绝对值 >{IMPACT_MATERIAL_THRESHOLD * 100:.1f}% · 已触发）"
        )

    fact = (
        f"截至 T-1 日（{td_disp}），受关联核心 ETF（如 {etf_label}）净赎回影响，"
        f"该标的承受了约占其日常成交额 {abs(value_pct):.2f}% 的机械性被动抛压。"
        f"穿透口径已剥离 ETF 总体规模幻觉，仅保留标的权重分摊后的个股冲击{material_note}。"
        f"请勿将 ETF 总申赎金额直接等同于个股威胁。"
    )

    return {
        "indicator_name": "核心ETF被动资金冲击当量",
        "value": value_pct,
        "fact_statement": fact,
        "calculation_logic": "Sum(各 ETF 净赎回额 × 标的权重) / 标的日均成交额",
        "source": SOURCE_ETF,
        "raw_metrics": {
            "inferred_trade_date": td_disp,
            "top_associated_etf": etf_label,
            "stock_weight_in_etf": top_weight,
            "implied_passive_sell_amount": round(total_passive_sell, 2),
            "stock_daily_amount_base": round(float(stock_amount), 2),
            "impact_ratio": round(impact_ratio, 6),
            "threat_urgency": urgency,
            "linked_etf_count": len(links),
            "contributing_etf_count": len(etf_contribs),
            "etf_contributions": etf_contribs[:5],
        },
    }


def describe_etf_redemption_ui_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    """静默态 UI · 无实质冲击或尚无链接时仍展示监控卡。"""
    if not payload:
        return {
            "mode": "silent",
            "reason": "no_payload",
            "message": "ETF 被动资金链接尚未建立 · 等待 08:30 盘前采集",
        }
    links = list(payload.get("etf_links") or [])
    if not links:
        return {
            "mode": "silent",
            "reason": "no_etf_links",
            "message": "未找到重仓该标的的核心 ETF · 增量扫描进行中",
            "links_count": 0,
        }
    metrics = compute_etf_redemption_metrics(payload)
    if metrics:
        rm = metrics.get("raw_metrics") or {}
        return {
            "mode": "active",
            "message": "实质被动抛压 · 已上报 T1",
            "impact_ratio": rm.get("impact_ratio"),
            "top_associated_etf": rm.get("top_associated_etf"),
            "inferred_trade_date": rm.get("inferred_trade_date"),
            "links_count": len(links),
        }

    # 有链接但冲击不足
    share_series = payload.get("etf_share_series") or {}
    latest_td = "—"
    for rows in share_series.values():
        if rows:
            td = str(rows[-1].get("trade_date") or "")
            if td and (latest_td == "—" or td > latest_td):
                latest_td = td
    if len(latest_td) == 8:
        latest_td = f"{latest_td[:4]}-{latest_td[4:6]}-{latest_td[6:8]}"

    return {
        "mode": "silent",
        "reason": "impact_below_threshold",
        "message": f"已监控 {len(links)} 只关联 ETF · T-1（{latest_td}）被动冲击 <1% · 无实质威胁",
        "links_count": len(links),
        "latest_trade_date": latest_td,
    }
