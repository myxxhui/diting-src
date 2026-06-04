"""T0 采集器（香港 Pod · 真实数据 · 无 mock · **严格准出**）。

[Ref: 28_ §3 · §9 完善期铁律]
**ok 仅当**：规划数据源已落地且验收字段齐全。**禁止**：代理源、词表无命中、
PVC 快照顶替、占位 payload 标 ok。
"""
from __future__ import annotations

import logging
import os
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
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return _block("margin_short_skew", "akshare 不可用")

    sym = symbol.zfill(6)[-6:]
    today = date.today()
    attempts = 0
    for offset in range(0, 14):
        if attempts >= 6:
            break
        attempts += 1
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            if _is_shanghai(sym):
                df = _ak_call(ak.stock_margin_detail_sse, date=ds)
                code_col, buy_col, short_col = "标的证券代码", "融资买入额", "融券余量"
                src = f"akshare stock_margin_detail_sse:{ds}"
            else:
                df = _ak_call(ak.stock_margin_detail_szse, date=ds)
                code_col, buy_col, short_col = "证券代码", "融资买入额", "融券余量"
                src = f"akshare stock_margin_detail_szse:{ds}"
        except Exception as exc:
            continue
        if df is None or df.empty or code_col not in df.columns:
            continue
        sub = df[df[code_col].astype(str).str.zfill(6) == sym]
        if sub.empty:
            continue
        r0 = sub.iloc[0]
        fin = float(r0.get(buy_col, 0) or 0)
        short = float(r0.get(short_col, 0) or 0)
        bal = float(r0.get("融资余额", 0) or 0) if "融资余额" in r0.index else None
        skew = short / fin if fin > 0 else None
        return _ok(
            "margin_short_skew",
            {
                "trade_date": ds,
                "margin_buy": fin,
                "short_balance": short,
                "margin_balance": bal,
                "skew": round(skew, 6) if skew is not None else None,
            },
            src,
        )
    return _block("margin_short_skew", "近12交易日两融日表均无该标的")


def _collect_block_trade(symbol: str) -> dict[str, Any]:
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return _block("block_trade_discount", "akshare 不可用")

    sym = symbol.zfill(6)[-6:]
    end = date.today()
    start = end - timedelta(days=90)
    dz = _ak_call(
        ak.stock_dzjy_mrmx,
        symbol="A股",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if dz is None or dz.empty:
        return _block("block_trade_discount", "近90日A股大宗明细为空")
    code_col = "证券代码" if "证券代码" in dz.columns else None
    if not code_col:
        return _block("block_trade_discount", "大宗表缺证券代码列")
    sub = dz[dz[code_col].astype(str).str.zfill(6).str.endswith(sym)]
    if sub.empty:
        return _block("block_trade_discount", f"近90日无{sym}大宗成交记录")
    last = sub.iloc[-1]
    disc = float(last.get("折溢率", 0) or 0)
    return _ok(
        "block_trade_discount",
        {
            "discount_pct": disc,
            "amount": float(last.get("成交额", 0) or 0),
            "trade_date": str(last.get("交易日期", "")),
        },
        "akshare stock_dzjy_mrmx A股过滤",
    )


def _collect_retail_concentration(symbol: str) -> dict[str, Any]:
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return _block("retail_concentration", "akshare 不可用")

    sym = symbol.zfill(6)[-6:]
    df = _ak_call(ak.stock_zh_a_gdhs_detail_em, symbol=sym)
    if df is None or df.empty:
        return _block("retail_concentration", "股东户数表为空")
    row = df.iloc[0]
    holder = row.get("股东户数") or row.get("HOLDER_NUM")
    prev = row.get("上期股东户数") or row.get("PRE_HOLDER_NUM")
    chg = row.get("股东户数增幅") or row.get("HOLDER_NUM_CHANGE")
    as_of = str(row.get("股东户数统计截止日") or row.get("END_DATE") or "")
    if holder is None and prev is None:
        return _block_typed("retail_concentration", "B", "股东户数字段为空")
    year_digits = "".join(c for c in as_of if c.isdigit())[:4]
    if year_digits and int(year_digits) < 2023:
        return _block_typed(
            "retail_concentration",
            "C",
            f"股东户数截止日过旧({as_of})·非当前动态口径",
        )
    if chg is None:
        return _block_typed("retail_concentration", "C", "缺股东户数环比%字段")
    return _ok(
        "retail_concentration",
        {
            "holder_num": float(holder) if holder is not None else None,
            "prev_holder_num": float(prev) if prev is not None else None,
            "holder_num_change_pct": float(chg),
            "as_of": as_of,
        },
        "akshare stock_zh_a_gdhs_detail_em",
    )


def _collect_level2_super_order(symbol: str) -> dict[str, Any]:
    """东财个股资金流「超大单」5日净额（28_ §3.2 #18 · 非采购 L2）。"""
    from apps.copilot.modules.radar.t0.collectors._em_fetch import (
        fetch_individual_super_order_net,
    )

    sym = symbol.zfill(6)[-6:]
    for attempt in range(1, _LEVEL2_RETRIES + 1):
        em = fetch_individual_super_order_net(sym, days=5)
        if em and em.get("net_super_order_5d") is not None:
            return _ok("level2_super_order", em, "eastmoney:push2his/fflow/daykline")
        if attempt < _LEVEL2_RETRIES:
            time.sleep(_LEVEL2_RETRY_SLEEP)

    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return _block_typed("level2_super_order", "B", "akshare 不可用")

    market = "sh" if _is_shanghai(sym) else "sz"
    for attempt in range(1, _LEVEL2_RETRIES + 1):
        df = _ak_call(ak.stock_individual_fund_flow, stock=sym, market=market)
        if df is not None and not df.empty:
            col = "超大单净流入-净额"
            if col not in df.columns:
                break
            tail = df.tail(5)
            payload = {
                "net_super_order_5d": float(tail[col].sum()),
                "days": len(tail),
                "last_date": str(tail.iloc[-1].get("日期", "")),
            }
            return _ok("level2_super_order", payload, "akshare stock_individual_fund_flow")
        if attempt < _LEVEL2_RETRIES:
            time.sleep(_LEVEL2_RETRY_SLEEP)

    return _block_typed(
        "level2_super_order",
        "B",
        f"东财超大单 {_LEVEL2_RETRIES} 轮均失败（禁止快照顶替 ok）",
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


def _collect_etf_redemption_impact() -> dict[str, Any]:
    """科技/电子类 ETF 周净申赎（28_ §3.2 #24 · 须有 share_change）。"""
    import re

    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_etf_spot_rows

    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return _block_typed("etf_redemption_impact", "B", "akshare 不可用")

    spot = _ak_call_timeout(ak.fund_etf_spot_em, _AK_TIMEOUT_ETF)
    if spot is not None and not spot.empty:
        rows = _etf_rows_from_spot_df(spot)
        if rows and any(r.get("share_change") is not None for r in rows):
            return _ok("etf_redemption_impact", {"etf_samples": rows}, "akshare fund_etf_spot_em")

    spot_rows = fetch_etf_spot_rows(max_pages=5)
    if spot_rows:
        pat = re.compile(r"科技|电子|通信|AI|芯片|算力|半导体|5G", re.I)
        matched = [r for r in spot_rows if pat.search(str(r.get("name") or ""))]
        if matched:
            return _block_typed(
                "etf_redemption_impact",
                "C",
                "push2delay ETF 列表无周份额变动字段·禁止仅份额数 ok",
            )

    if spot is None or spot.empty:
        return _block_typed("etf_redemption_impact", "B", "ETF现货表为空")
    return _block_typed("etf_redemption_impact", "C", "缺 ETF 周净申赎(share_change)字段")


def _collect_parent_honhai_revenue() -> dict[str, Any]:
    return _block_typed(
        "parent_honhai_revenue",
        "A",
        "TWSE Open API 2317 月营收未实现（禁止 akshare HK 替代标 ok）",
    )


def _collect_unimplemented_l3(key: str, spec: str) -> dict[str, Any]:
    return _block_typed(key, "A", spec)


def collect_l4_micro(symbol: str) -> list[dict[str, Any]]:
    """#15-17,19-21,25 · K 线自算 + akshare 补充。"""
    from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_250d

    out: list[dict[str, Any]] = []
    bars = fetch_bars_250d(symbol)
    if not bars or len(bars) < 25:
        for k in (
            "qmt_atr_trailing",
            "volume_price_div",
            "turnover_acceleration",
            "tech_beta_correlation",
        ):
            out.append(_block(k, "K线不足250日·market_quote/akshare均失败"))
        return out

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    vols = [b.volume for b in bars]

    trs: list[float] = []
    for i in range(1, min(21, len(bars))):
        tr = max(
            highs[-i] - lows[-i],
            abs(highs[-i] - closes[-i - 1]),
            abs(lows[-i] - closes[-i - 1]),
        )
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.0
    peak = max(highs[-60:]) if len(highs) >= 60 else max(highs)
    cur = closes[-1]
    atr_mult = (peak - cur) / atr if atr > 0 else None
    out.append(
        _ok(
            "qmt_atr_trailing",
            {"atr20": round(atr, 4), "peak_price": peak, "current": cur, "atr_multiple": atr_mult},
            "HK Pod·250日K线自算ATR",
        )
    )

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

    v3 = sum(vols[-3:]) / 3 if len(vols) >= 3 else 0
    v60 = sum(vols[-60:]) / 60 if len(vols) >= 60 else 1e-9
    out.append(
        _ok(
            "turnover_acceleration",
            {"vol_avg_3d": v3, "vol_avg_60d": v60, "accel": round(v3 / v60, 4) if v60 else None},
            "HK Pod·成交量3/60均值比",
        )
    )

    rets = []
    for i in range(-11, -1):
        if closes[i - 1] > 0:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
    vol10 = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else None
    out.append(
        _block_typed(
            "tech_beta_correlation",
            "A",
            "601138与中证1000/AI指数10日滚动ρ未实现（禁止用波动率顶替）",
        )
    )

    try:
        import akshare as ak  # type: ignore

        nb = None
        for _ in range(2):
            nb = _ak_call(ak.stock_hsgt_individual_em, symbol=symbol)
            if nb is not None and not nb.empty:
                break
        if nb is not None and not nb.empty:
            tail = nb.tail(3)
            if "持股数量变化" not in tail.columns:
                out.append(_block_typed("northbound_net_flow", "C", "表结构缺持股数量变化列"))
            else:
                net = float(tail["持股数量变化"].sum())
                out.append(
                    _ok(
                        "northbound_net_flow",
                        {"net_3d_shares_change": net, "rows": len(tail)},
                        "akshare stock_hsgt_individual_em",
                    )
                )
        else:
            out.append(_block_typed("northbound_net_flow", "B", "北向个股表为空或超时"))
    except Exception as exc:
        out.append(_block("northbound_net_flow", f"akshare失败:{exc}"[:200]))

    out.append(_collect_margin_skew(symbol))
    out.append(_collect_block_trade(symbol))
    out.append(_collect_level2_super_order(symbol))
    return out


def collect_l3_daily(symbol: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        import akshare as ak  # type: ignore

        fx = _ak_call(ak.fx_spot_quote)
        if fx is not None and not fx.empty:
            usd = fx[fx["货币对"].astype(str).str.contains("USD/CNY", na=False)]
            if not usd.empty:
                rate = float(usd.iloc[0].get("最新价", 0) or 0)
                if rate > 0:
                    out.append(
                        _block_typed(
                            "exchange_rate_impact",
                            "C",
                            f"仅现货{rate}·28_要求30日升贬值%序列未实现",
                        )
                    )
                else:
                    out.append(_block_typed("exchange_rate_impact", "B", "USD/CNY 最新价为0或无效"))
            else:
                out.append(_block_typed("exchange_rate_impact", "B", "fx_spot_quote 无 USD/CNY 行"))
        else:
            out.append(_block_typed("exchange_rate_impact", "B", "fx_spot_quote 空/失败"))
        if not any(x["probe_key"] == "exchange_rate_impact" for x in out):
            out.append(_block_typed("exchange_rate_impact", "B", "fx 接口未调用"))
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
        ins = _headline_probe(titles, "insider_sell_actual", ("减持",), news_source)
        if ins.get("ok"):
            out.append(
                _block_typed(
                    "insider_sell_actual",
                    "A",
                    "巨潮减持解析·占总股本%未实现（禁止仅标题命中 ok）",
                )
            )
        else:
            out.append(ins)
    else:
        out.append(_block_typed("gb200_iteration_node", "B", "标的公告+快讯均为空"))
        out.append(_block_typed("insider_sell_actual", "B", "标的公告+快讯均为空"))

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

    for k, msg in (
        ("gross_margin_trend", "财报毛利率 QoQ 解析未实现（禁止 financial_abstract 原表顶替）"),
        ("inventory_turnover", "存货周转天数未实现"),
        ("contract_liabilities", "合同负债环比%未实现"),
        ("related_party_trans", "D1 关联交易表环比未接入"),
    ):
        out.append(_collect_unimplemented_l3(k, msg))

    out.append(_collect_parent_honhai_revenue())
    out.append(_collect_cpi_ppi_spread())
    out.append(_collect_retail_concentration(symbol))
    out.append(_collect_etf_redemption_impact())
    return out


def collect_all_t0(symbol: str) -> list[dict[str, Any]]:
    return collect_l4_micro(symbol) + collect_l3_daily(symbol)
