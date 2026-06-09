"""T0 采集器（香港 Pod · 真实数据 · 无 mock · **严格准出**）。

[Ref: 28_ §3 · §9 完善期铁律]
**ok 仅当**：规划数据源已落地且验收字段齐全。**禁止**：代理源、词表无命中、
PVC 快照顶替、占位 payload 标 ok。
"""
from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import date, datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)

_AK_TIMEOUT = float(os.environ.get("EXECUTING_T0_AKSHARE_TIMEOUT_SEC", "20"))
_AK_TIMEOUT_ETF = float(os.environ.get("EXECUTING_T0_ETF_TIMEOUT_SEC", "60"))
_LEVEL2_RETRIES = max(1, int(os.environ.get("EXECUTING_LEVEL2_RETRIES", "3")))
_LEVEL2_RETRY_SLEEP = float(os.environ.get("EXECUTING_LEVEL2_RETRY_SLEEP_SEC", "2"))


def _ak_call_timeout(
    fn: Callable[..., Any],
    timeout_sec: float,
    *args: Any,
    **kwargs: Any,
) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=timeout_sec)
        except FuturesTimeout:
            logger.warning("akshare 超时 %ss: %s", timeout_sec, getattr(fn, "__name__", fn))
            return None
        except Exception as exc:
            logger.warning("akshare 异常 %s: %s", getattr(fn, "__name__", fn), exc)
            return None


def _block(key: str, reason: str) -> dict[str, Any]:
    return {"probe_key": key, "ok": False, "blocker": reason, "payload": None}


def _block_typed(key: str, code: str, reason: str) -> dict[str, Any]:
    """code: A=未实现 B=渠道失败 C=源错位 D=判定过窄 E=已证无事件(仅用于仍missing时)"""
    return _block(key, f"[{code}] {reason}")


def _ok(key: str, payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {"probe_key": key, "ok": True, "blocker": None, "payload": payload, "source": source}


def _ak_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=_AK_TIMEOUT)
        except FuturesTimeout:
            logger.warning("akshare 超时 %ss: %s", _AK_TIMEOUT, getattr(fn, "__name__", fn))
            return None
        except Exception as exc:
            logger.warning(
                "akshare 异常 %s: %s",
                getattr(fn, "__name__", fn),
                exc,
            )
            return None


def _collect_smart_money_flow(symbol: str) -> dict[str, Any]:
    """#17 L2 主力大单 · Tushare moneyflow（废弃 northbound_net_flow）。"""
    from apps.copilot.modules.executing.smart_money_flow import (
        fetch_moneyflow_raw,
        tushare_token,
    )

    if not tushare_token():
        return _block_typed(
            "smart_money_flow",
            "A",
            "未配置 TUSHARE_TOKEN · 待用户提供后启用采集",
        )
    try:
        payload = fetch_moneyflow_raw(symbol)
        if len(payload.get("moneyflow_rows") or []) < 3:
            return _block_typed(
                "smart_money_flow",
                "C",
                f"moneyflow 行数不足 3（实际 {len(payload.get('moneyflow_rows') or [])}）",
            )
        if not payload.get("free_float_shares"):
            return _block_typed(
                "smart_money_flow",
                "C",
                "daily_basic 缺 free_share/float_share",
            )
        return _ok(
            "smart_money_flow",
            payload,
            "Tushare API (moneyflow+daily_basic)",
        )
    except ImportError:
        return _block_typed("smart_money_flow", "A", "未安装 tushare 包")
    except Exception as exc:
        return _block("smart_money_flow", f"Tushare moneyflow 失败:{exc}"[:200])


def _is_shanghai(symbol: str) -> bool:
    sym = symbol.zfill(6)[-6:]
    return sym.startswith(("5", "6", "9"))


def _cninfo_headlines(symbol: str, *, limit: int = 120, max_pages: int = 4) -> list[str]:
    from apps.cryo_guard.cninfo_client import iter_cninfo_announcements

    end = date.today()
    start = end - timedelta(days=365)
    titles: list[str] = []
    for item in iter_cninfo_announcements(
        symbol.zfill(6)[-6:],
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        max_pages=max_pages,
        throttle_sec=0.15,
    ):
        title = str(item.get("announcementTitle") or item.get("title") or "").strip()
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def _fetch_titles(symbol: str) -> tuple[list[str], str]:
    """标的公告优先（巨潮），快讯补充；禁止仅用 10 条快讯代表「近一年」。"""
    import akshare as ak  # type: ignore

    sym = symbol.zfill(6)[-6:]
    titles: list[str] = []
    try:
        titles = _cninfo_headlines(sym, limit=120, max_pages=4)
        source = "cninfo:iter_cninfo_announcements"
    except Exception as exc:
        logger.warning("巨潮公告失败: %s", exc)
        source = "cninfo:error"
    try:
        news = _ak_call(ak.stock_news_em, symbol=sym)
        if news is not None and not news.empty and "新闻标题" in news.columns:
            for t in news.head(30)["新闻标题"].astype(str).tolist():
                if t and t not in titles:
                    titles.append(t)
            if source.startswith("cninfo:error"):
                source = "akshare stock_news_em"
            else:
                source = f"{source}+stock_news_em"
    except Exception as exc:
        logger.warning("stock_news_em 失败: %s", exc)
    return titles, source


def _fetch_industry_headlines(*, limit: int = 80) -> tuple[list[str], str]:
    """产业链/宏观快讯池（非 601138 专用，供 nvda/tsmc/smci 等）。"""
    import akshare as ak  # type: ignore

    df = _ak_call(ak.stock_news_main_cx)
    if df is None or df.empty:
        return [], "akshare stock_news_main_cx:empty"
    col = "标题" if "标题" in df.columns else df.columns[0]
    titles = [str(x) for x in df[col].head(limit).tolist() if str(x).strip()]
    return titles, "akshare stock_news_main_cx"


def _headline_probe(
    titles: list[str],
    key: str,
    keywords: tuple[str, ...],
    source: str,
    *,
    titles_scanned: int | None = None,
) -> dict[str, Any]:
    """仅关键词命中可 ok；无命中 = missing（禁止「扫过了」冒充 ok）。"""
    n = titles_scanned if titles_scanned is not None else len(titles)
    matched = [t for t in titles if any(k in t for k in keywords)]
    if matched:
        return _ok(
            key,
            {"matched_headlines": matched[:8], "match_count": len(matched), "titles_scanned": n},
            source,
        )
    if n > 0:
        return _block_typed(
            key,
            "D",
            f"已扫{n}条·无规划关键词命中（非「无披露」准出）",
        )
    return _block_typed(key, "B", "公告/新闻管道返回0条")


def _collect_margin_skew(symbol: str) -> dict[str, Any]:
    """#19 · Tushare margin_detail · 由 l4-margin-skew-morning Cron 落 PG（T+1）。"""
    return _block_typed(
        "margin_short_skew",
        "A",
        "需 Tushare 两融 PG 底库 · 请运行 l4-margin-skew-morning（周二至周六 08:30）",
    )


def _collect_tech_beta_correlation(symbol: str) -> dict[str, Any]:
    """#25 · Tushare daily + index_daily · 由 l4-beta-correlation-eod Cron 落 PG。"""
    return _block_typed(
        "tech_beta_correlation",
        "A",
        "需 Tushare 板块β PG 底库 · 请运行 l4-beta-correlation-eod（15:30 盘后）",
    )


def _collect_turnover_acceleration(symbol: str) -> dict[str, Any]:
    """#20 · Tushare daily_basic turnover_rate_f · 由 l4-turnover-accel-eod Cron 落 PG。"""
    return _block_typed(
        "turnover_acceleration",
        "A",
        "需 Tushare turnover PG 底库 · 请运行 l4-turnover-accel-eod（15:30 盘后）",
    )


def _collect_block_trade(symbol: str) -> dict[str, Any]:
    """#21 · Tushare block_trade · 由 l4-block-trade-eod Cron 落 PG（18:00）。"""
    return _block_typed(
        "block_trade_discount",
        "A",
        "需 Tushare 大宗 PG 底库 · 请运行 l4-block-trade-eod（18:00 盘后）",
    )


_INSIDER_PCT_RE = re.compile(
    r"(?:不超过|不超)\s*([\d.]+)\s*%|(?:拟)?减持(?:股份)?[^%]{0,24}?([\d.]+)\s*%"
)


def _parse_insider_sell_pct(titles: list[str]) -> float | None:
    """从巨潮/快讯标题解析减持占股本比例上限。"""
    best: float | None = None
    for title in titles:
        if "减持" not in title:
            continue
        m0 = re.search(r"不超(?:过)?\s*([\d.]+)\s*%", title)
        if m0:
            try:
                pct = float(m0.group(1))
                best = pct if best is None else max(best, pct)
                continue
            except (TypeError, ValueError):
                pass
        for m in _INSIDER_PCT_RE.finditer(title):
            for g in m.groups():
                if not g:
                    continue
                try:
                    pct = float(g)
                except (TypeError, ValueError):
                    continue
                best = pct if best is None else max(best, pct)
    return best


def _collect_insider_sell_actual(symbol: str) -> dict[str, Any]:
    """#23 · Tushare stk_holdertrade · 由 l4-insider-sell-eod Cron 落 PG（20:30）。"""
    return _block_typed(
        "insider_sell_actual",
        "A",
        "需 stk_holdertrade PG 底库 · 请运行 l4-insider-sell-eod（20:30 盘后）",
    )


def _collect_retail_concentration(symbol: str) -> dict[str, Any]:
    """#22 · AkShare 股东户数 · 由 l4-retail-concentration-eod Cron 落 PG（20:30）。"""
    return _block_typed(
        "retail_concentration",
        "A",
        "需股东户数 PG 快照底库 · 请运行 l4-retail-concentration-eod（20:30 盘后）",
    )


def _collect_financial_kpi_probe(symbol: str, key: str, field: str, label: str) -> dict[str, Any]:
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_financial_kpis

    kpi = fetch_financial_kpis(symbol)
    if not kpi:
        return _block_typed(key, "B", f"东财 RPT_F10_FINANCE_MAINFINADATA 无{label}")
    val = kpi.get(field)
    if val is None:
        return _block_typed(key, "C", f"财报指标缺{label}字段")
    payload: dict[str, Any] = {
        "report_date": kpi.get("report_date"),
        field: val,
    }
    if field == "gross_margin_pct":
        payload["gross_margin_qoq_pct"] = kpi.get("gross_margin_qoq_pct")
    elif field == "contract_liabilities":
        payload["contract_liabilities_qoq_pct"] = kpi.get("contract_liabilities_qoq_pct")
    return _ok(key, payload, "eastmoney:RPT_F10_FINANCE_MAINFINADATA")


def _collect_level2_super_order(symbol: str) -> dict[str, Any]:
    """#18 · Tushare moneyflow elg_amount · 由 l2-super-order-eod Cron 落 PG。"""
    return _block_typed(
        "level2_super_order",
        "A",
        "需 Tushare PG 底库 · 请运行 l2-super-order-eod 或 l2-super-order-backfill",
    )


def _collect_cloud_capex_sec() -> dict[str, Any]:
    """SEC EDGAR companyfacts · 四云商 CapEx（28_ §3.1 #4）。"""
    import json
    import urllib.request

    # [Ref: 28_ §3.1 #4 · SEC data.sec.gov]
    ciks = {
        "MSFT": "0000789019",
        "AMZN": "0001018724",
        "GOOGL": "0001652044",
        "META": "0001326801",
    }
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "Diting executing/1.0 (contact: diting-copilot)")
    rows: list[dict[str, Any]] = []
    for ticker, cik in ciks.items():
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("SEC %s 失败: %s", ticker, exc)
            continue
        facts = (data.get("facts") or {}).get("us-gaap") or {}
        capex_node = facts.get("CapitalExpenditure") or facts.get("PaymentsToAcquirePropertyPlantAndEquipment")
        if not capex_node:
            continue
        units = capex_node.get("units") or {}
        usd = units.get("USD") or []
        if not usd:
            continue
        latest = max(usd, key=lambda x: x.get("end", ""))
        rows.append(
            {
                "ticker": ticker,
                "capex_usd": latest.get("val"),
                "period_end": latest.get("end"),
                "form": latest.get("form"),
            }
        )
    if not rows:
        return _block_typed(
            "cloud_capex_consensus",
            "B",
            "SEC EDGAR 四云商 CapEx 均未拉取成功（非「云厂商未披露」）",
        )
    total = sum(float(r["capex_usd"]) for r in rows if r.get("capex_usd") is not None)
    return _ok(
        "cloud_capex_consensus",
        {"hyperscaler_capex": rows, "total_capex_usd": total, "count": len(rows)},
        "sec.gov companyfacts CapitalExpenditure",
    )


def _collect_mgmt_and_core_team(symbol: str) -> dict[str, Any]:
    """巨潮公告全量扫描 + 董监高关键词（28_ §3.1 #12）。"""
    sym = symbol.zfill(6)[-6:]
    titles = _cninfo_headlines(sym, limit=200, max_pages=5)
    if not titles:
        return _block_typed("mgmt_and_core_team", "B", "巨潮公告管道0条·无法判断有无人事变动")
    mgmt_kw = (
        "辞职",
        "辞任",
        "任免",
        "董事",
        "监事",
        "高管",
        "总裁",
        "总经理",
        "董事会",
        "高级管理人员",
        "人事变动",
        "聘任",
    )
    matched = [t for t in titles if any(k in t for k in mgmt_kw)]
    source = "cninfo:iter_cninfo_announcements"
    if matched:
        return _ok(
            "mgmt_and_core_team",
            {
                "events": matched[:12],
                "event_count": len(matched),
                "titles_scanned": len(titles),
            },
            source,
        )
    # 28_ 验收：「变更事件列表或『无』」— 巨潮全扫后 events=[] 为合法负结果
    return _ok(
        "mgmt_and_core_team",
        {
            "events": [],
            "event_count": 0,
            "titles_scanned": len(titles),
            "disclosure": "cninfo_no_mgmt_keyword_in_365d",
        },
        source,
    )


def _collect_cpi_ppi_spread() -> dict[str, Any]:
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return _block("cpi_ppi_spread", "akshare 不可用")

    cpi, ppi = None, None
    for _ in range(3):
        cpi = _ak_call(ak.macro_china_cpi)
        ppi = _ak_call(ak.macro_china_ppi)
        if cpi is not None and not cpi.empty and ppi is not None and not ppi.empty:
            break
    if cpi is None or cpi.empty or ppi is None or ppi.empty:
        return _block_typed("cpi_ppi_spread", "B", "东财宏观CPI/PPI当次空/超时·非「中国无宏观数据」")
    cpi_yoy = float(cpi.iloc[0].get("全国-同比增长", 0) or 0)
    ppi_yoy = float(ppi.iloc[0].get("当月同比增长", 0) or 0)
    return _ok(
        "cpi_ppi_spread",
        {
            "cpi_yoy_pct": cpi_yoy,
            "ppi_yoy_pct": ppi_yoy,
            "spread_ppt": round(cpi_yoy - ppi_yoy, 4),
            "cpi_month": str(cpi.iloc[0].get("月份", "")),
            "ppi_month": str(ppi.iloc[0].get("月份", "")),
        },
        "akshare macro_china_cpi + macro_china_ppi",
    )


def _etf_rows_from_spot_df(spot: Any) -> list[dict[str, Any]]:
    name_col = "名称" if "名称" in spot.columns else spot.columns[1]
    code_col = "代码" if "代码" in spot.columns else spot.columns[0]
    share_col = next((c for c in spot.columns if "份额" in str(c)), None)
    chg_col = next((c for c in spot.columns if "增减" in str(c) or "变动" in str(c)), None)
    mask = spot[name_col].astype(str).str.contains(
        "科技|电子|通信|AI|芯片|算力|半导体|5G",
        na=False,
        regex=True,
    )
    sub = spot[mask].head(5)
    rows: list[dict[str, Any]] = []
    for _, r in sub.iterrows():
        rows.append(
            {
                "code": str(r.get(code_col, "")),
                "name": str(r.get(name_col, "")),
                "shares": float(r[share_col]) if share_col and r.get(share_col) is not None else None,
                "share_change": float(r[chg_col]) if chg_col and r.get(chg_col) is not None else None,
            }
        )
    return rows


def _collect_etf_redemption_impact(symbol: str) -> dict[str, Any]:
    """#24 · Tushare fund_share + fund_portfolio · 由 l4-etf-redemption-morning Cron 落 PG（08:30 T+1）。"""
    return _block_typed(
        "etf_redemption_impact",
        "A",
        "需 ETF 穿透 PG 底库 · 请运行 l4-etf-redemption-morning（周二至周六 08:30 盘前）",
    )


def _collect_parent_honhai_revenue() -> dict[str, Any]:
    return _block_typed(
        "parent_honhai_revenue",
        "A",
        "TWSE Open API 2317 月营收未实现（禁止 akshare HK 替代标 ok）",
    )


def _collect_unimplemented_l3(key: str, spec: str) -> dict[str, Any]:
    return _block_typed(key, "A", spec)


def _daily_rows_to_quote_bars(rows: list[Any]) -> list[Any]:
    from apps.state_watch.probes.datasource.quote_adapter import Bar

    return [
        Bar(
            date=r.trade_date.isoformat(),
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
        )
        for r in rows
    ]


def collect_l4_micro(
    symbol: str,
    *,
    daily_bar_rows: list[Any] | None = None,
    entry_date: Any = None,
) -> list[dict[str, Any]]:
    """#15-17,19-21,25 · K 线自算 + akshare 补充。"""
    from apps.copilot.modules.executing.collectors.daily_bars import MIN_BARS_ACCEPT
    from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
        AtrTrailingError,
        SOURCE_PG,
        process_qmt_atr_trailing_from_rows,
    )
    from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_250d

    out: list[dict[str, Any]] = []
    qmt_from_pg = False
    if daily_bar_rows and len(daily_bar_rows) >= MIN_BARS_ACCEPT:
        bars = _daily_rows_to_quote_bars(daily_bar_rows)
        try:
            atr_payload = process_qmt_atr_trailing_from_rows(
                daily_bar_rows,
                entry_date,
                source=SOURCE_PG,
            )
            out.append(
                _ok(
                    "qmt_atr_trailing",
                    atr_payload,
                    atr_payload.get("source", SOURCE_PG),
                )
            )
            qmt_from_pg = True
        except AtrTrailingError as exc:
            out.append(_block("qmt_atr_trailing", str(exc)[:200]))
            qmt_from_pg = True
    else:
        bars = fetch_bars_250d(symbol)

    if not bars or len(bars) < 25:
        for k in (
            "qmt_atr_trailing",
            "volume_price_div",
        ):
            if k == "qmt_atr_trailing" and qmt_from_pg:
                continue
            out.append(_block(k, "K线不足250日·market_quote/akshare均失败"))
        if not qmt_from_pg:
            return out

    if not qmt_from_pg:
        from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow

        fallback_rows = [
            DailyBarRow(
                trade_date=__import__("datetime").date.fromisoformat(b.date[:10]),
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=float(b.volume),
            )
            for b in bars
        ]
        try:
            atr_payload = process_qmt_atr_trailing_from_rows(
                fallback_rows,
                entry_date,
                source="HK Pod·250日K线 · market_quote",
            )
            out.append(
                _ok(
                    "qmt_atr_trailing",
                    atr_payload,
                    atr_payload.get("source", "HK Pod·250日K线"),
                )
            )
        except AtrTrailingError as exc:
            out.append(_block("qmt_atr_trailing", str(exc)[:200]))

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    recent = bars[-10:]
    up_vol = sum(b.volume for b in recent if b.close >= b.open)
    down_vol = sum(b.volume for b in recent if b.close < b.open) or 1e-9
    ratio = up_vol / down_vol if down_vol else None
    out.append(
        _ok(
            "volume_price_div",
            {"up_volume": up_vol, "down_volume": down_vol, "ratio": round(ratio, 4) if ratio else None},
            "HK Pod·10日涨跌日量比",
        )
    )

    out.append(_collect_tech_beta_correlation(symbol))
    out.append(_collect_smart_money_flow(symbol))

    out.append(_collect_margin_skew(symbol))
    out.append(_collect_turnover_acceleration(symbol))
    out.append(_collect_block_trade(symbol))
    out.append(_collect_level2_super_order(symbol))
    return out


def collect_l3_daily(symbol: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_usd_cny_30d_pct

    try:
        fx30 = fetch_usd_cny_30d_pct()
        if fx30 and fx30.get("pct_30d") is not None:
            out.append(
                _ok(
                    "exchange_rate_impact",
                    fx30,
                    "akshare currency_boc_sina USD 30d",
                )
            )
        else:
            import akshare as ak  # type: ignore

            fx = _ak_call(ak.fx_spot_quote)
            if fx is not None and not fx.empty:
                usd = fx[fx["货币对"].astype(str).str.contains("USD/CNY", na=False)]
                if not usd.empty:
                    row0 = usd.iloc[0]
                    rate = float(
                        row0.get("买报价") or row0.get("卖报价") or row0.get("最新价") or 0
                    )
                    if rate > 0:
                        out.append(
                            _block_typed(
                                "exchange_rate_impact",
                                "C",
                                f"仅现货{rate}·30日序列未获取",
                            )
                        )
                    else:
                        out.append(_block_typed("exchange_rate_impact", "B", "USD/CNY 报价无效"))
                else:
                    out.append(_block_typed("exchange_rate_impact", "B", "fx_spot_quote 无 USD/CNY 行"))
            else:
                out.append(_block_typed("exchange_rate_impact", "B", "fx 接口空/失败"))
    except Exception as exc:
        out.append(_block("exchange_rate_impact", str(exc)[:200]))

    try:
        import akshare as ak  # type: ignore

        copper = _ak_call(
            ak.futures_main_sina,
            symbol="CU0",
            start_date=(date.today() - timedelta(days=40)).strftime("%Y%m%d"),
        )
        if copper is not None and len(copper) >= 2:
            c0 = float(copper.iloc[-1]["收盘价"])
            c30 = float(copper.iloc[max(0, len(copper) - 30)]["收盘价"])
            chg = (c0 - c30) / c30 * 100 if c30 else None
            out.append(
                _ok(
                    "copper_cost_pressure",
                    {"close": c0, "pct_30d": round(chg, 2) if chg is not None else None},
                    "akshare futures_main_sina CU0",
                )
            )
        else:
            out.append(_block("copper_cost_pressure", "沪铜序列不足"))
    except Exception as exc:
        out.append(_block("copper_cost_pressure", str(exc)[:200]))

    titles, news_source = _fetch_titles(symbol)

    if titles:
        out.append(
            _headline_probe(
                titles,
                "gb200_iteration_node",
                ("GB200", "工业富联", "NVL", "量产", "服务器", "AI", "数据中心"),
                news_source,
            )
        )
        sell_titles = [t for t in titles if "减持" in t]
        if sell_titles:
            out.append(
                _block_typed(
                    "insider_sell_actual",
                    "A",
                    "禁止用公告标题冒充实际减持 · 见 l4-insider-sell-eod/stk_holdertrade",
                )
            )
        else:
            out.append(_collect_insider_sell_actual(symbol))
    else:
        out.append(_block_typed("gb200_iteration_node", "B", "标的公告+快讯均为空"))
        out.append(_block_typed("insider_sell_actual", "B", "标的公告+快讯均为空 · 见 l4-insider-sell-eod"))

    out.append(_collect_mgmt_and_core_team(symbol))
    out.append(_collect_cloud_capex_sec())

    out.append(
        _collect_unimplemented_l3(
            "nvda_gpu_leadtime",
            "分销商 API / external_facts 未实现（禁止行业快讯词表顶替）",
        )
    )
    out.append(
        _collect_unimplemented_l3(
            "tsmc_cowos_capacity",
            "巨潮/台媒→vLLM 抽取 CoWoS 四字段未实现",
        )
    )
    out.append(
        _collect_unimplemented_l3(
            "smci_quanta_share",
            "纪要 PDF→DeepSeek 份额抽取未实现",
        )
    )

    out.append(
        _collect_financial_kpi_probe(
            symbol, "gross_margin_trend", "gross_margin_pct", "毛利率"
        )
    )
    out.append(
        _collect_financial_kpi_probe(
            symbol, "inventory_turnover", "inventory_turnover_days", "存货周转天数"
        )
    )
    out.append(
        _collect_financial_kpi_probe(
            symbol, "contract_liabilities", "contract_liabilities", "合同负债"
        )
    )
    out.append(_collect_unimplemented_l3("related_party_trans", "D1 关联交易表环比未接入"))

    out.append(_collect_parent_honhai_revenue())
    out.append(_collect_cpi_ppi_spread())
    out.append(_collect_retail_concentration(symbol))
    out.append(_collect_etf_redemption_impact(symbol))
    return out


def collect_qmt_atr_t0(
    symbol: str,
    *,
    daily_bar_rows: list[Any] | None = None,
    entry_date: Any = None,
) -> list[dict[str, Any]]:
    """T0 当前仅采集 #15 qmt_atr_trailing（不拉其余 24 探针外网）。"""
    from apps.copilot.modules.executing.collectors.daily_bars import (
        DailyBarRow,
        MIN_BARS_ACCEPT,
    )
    from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
        AtrTrailingError,
        SOURCE_PG,
        process_qmt_atr_trailing_from_rows,
    )
    from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_250d

    out: list[dict[str, Any]] = []
    if daily_bar_rows and len(daily_bar_rows) >= MIN_BARS_ACCEPT:
        try:
            atr_payload = process_qmt_atr_trailing_from_rows(
                daily_bar_rows,
                entry_date,
                source=SOURCE_PG,
            )
            out.append(
                _ok(
                    "qmt_atr_trailing",
                    atr_payload,
                    atr_payload.get("source", SOURCE_PG),
                )
            )
            return out
        except AtrTrailingError as exc:
            out.append(_block("qmt_atr_trailing", str(exc)[:200]))
            return out

    bars = fetch_bars_250d(symbol)
    if not bars or len(bars) < MIN_BARS_ACCEPT:
        out.append(_block("qmt_atr_trailing", "K线不足250日·market_quote/akshare均失败"))
        return out

    fallback_rows = [
        DailyBarRow(
            trade_date=__import__("datetime").date.fromisoformat(b.date[:10]),
            open=float(b.open),
            high=float(b.high),
            low=float(b.low),
            close=float(b.close),
            volume=float(b.volume),
        )
        for b in bars
    ]
    try:
        atr_payload = process_qmt_atr_trailing_from_rows(
            fallback_rows,
            entry_date,
            source="HK Pod·250日K线 · market_quote",
        )
        out.append(
            _ok(
                "qmt_atr_trailing",
                atr_payload,
                atr_payload.get("source", "HK Pod·250日K线"),
            )
        )
    except AtrTrailingError as exc:
        out.append(_block("qmt_atr_trailing", str(exc)[:200]))
    return out


def collect_all_t0(
    symbol: str,
    *,
    daily_bar_rows: list[Any] | None = None,
    entry_date: Any = None,
) -> list[dict[str, Any]]:
    return collect_qmt_atr_t0(
        symbol, daily_bar_rows=daily_bar_rows, entry_date=entry_date
    )
