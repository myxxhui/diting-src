"""东方财富 datacenter / push2 直连（跟随 302 · 重试 · no-mock）。

akshare 1.17.1 对部分东财接口未 follow redirect（push2→push2delay），
且 ``stock_gpzy_pledge_ratio_detail_em`` 需翻 252 页，启动期 Cron 不可接受。

[Ref: 27_ §2 · 21_行情数据源]
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_UA = os.environ.get(
    "RADAR_T0_EM_USER_AGENT",
    "Mozilla/5.0 (compatible; diting-radar/1.0)",
)
_RETRY = int(os.environ.get("RADAR_T0_EM_RETRY", "3"))
_TIMEOUT = float(os.environ.get("RADAR_T0_EM_TIMEOUT_SEC", "25"))
_THROTTLE = float(os.environ.get("RADAR_T0_EM_THROTTLE_SEC", "0.35"))

_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
# push2 常 302→push2delay；境外 Pod 直连 push2 易 reset/502
_PUSH2 = os.environ.get(
    "RADAR_T0_EM_PUSH2_BASE",
    "https://push2delay.eastmoney.com",
).rstrip("/")
_SPOT_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
_SPOT_FIELDS = "f12,f14,f3,f6,f20,f100,f115"


def _sleep_throttle() -> None:
    if _THROTTLE > 0:
        time.sleep(_THROTTLE)


def em_get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    referer: str = "https://data.eastmoney.com/",
    retries: int | None = None,
) -> dict[str, Any] | None:
    """GET JSON · follow redirects · 指数退避重试。"""
    attempts = retries if retries is not None else _RETRY
    headers = {"User-Agent": _UA, "Referer": referer}
    last_err: Exception | None = None
    for i in range(attempts):
        if i:
            time.sleep(min(2.0 ** i, 8.0))
        try:
            with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
                resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200 or not resp.text.strip():
                last_err = RuntimeError(f"HTTP {resp.status_code} empty")
                continue
            if not resp.text.lstrip().startswith("{"):
                last_err = RuntimeError(f"非 JSON 响应: {resp.text[:80]!r}")
                continue
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("em_get_json 失败 (%s/%s) %s: %s", i + 1, attempts, url[:60], exc)
    logger.warning("em_get_json 放弃 %s: %s", url[:60], last_err)
    return None


def fetch_pledge_ratio(symbol: str) -> dict[str, Any] | None:
    """单标的质押比例 · datacenter RPT_CSDC_LIST（秒级）。"""
    sym = str(symbol).zfill(6)[-6:]
    payload = em_get_json(
        _DATACENTER,
        params={
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageSize": "3",
            "pageNumber": "1",
            "reportName": "RPT_CSDC_LIST",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(SECURITY_CODE="{sym}")',
        },
        referer="https://data.eastmoney.com/gpzy/pledgeRatio.aspx",
    )
    if not payload:
        return None
    rows = (payload.get("result") or {}).get("data") or []
    if not rows:
        return None
    row = rows[0]
    ratio = row.get("PLEDGE_RATIO")
    try:
        ratio_f = float(ratio)
        if ratio_f <= 1:
            ratio_f = round(ratio_f * 100, 4)
    except (TypeError, ValueError):
        ratio_f = None
    return {
        "status": "ok",
        "source": "eastmoney:RPT_CSDC_LIST",
        "pledge_ratio_pct": ratio_f,
        "trade_date": str(row.get("TRADE_DATE") or "")[:10],
        "industry": row.get("INDUSTRY"),
    }


def fetch_industry_boards() -> list[dict[str, Any]]:
    """行业板块列表 · push2delay（涨跌幅 f3）。"""
    data = em_get_json(
        f"{_PUSH2}/api/qt/clist/get",
        params={
            "pn": "1",
            "pz": "200",
            "po": "1",
            "np": "1",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fltt": "2",
            "invt": "2",
            "fid0": "f3",
            "fs": "m:90+t:2",
            "stat": "1",
            "fields": "f12,f14,f3,f62,f184",
        },
        referer="https://data.eastmoney.com/bkzj/hy.html",
    )
    if not data:
        return []
    diff = (data.get("data") or {}).get("diff") or []
    out: list[dict[str, Any]] = []
    for item in diff:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "board_code": item.get("f12"),
                "board_name": item.get("f14"),
                "pct_chg": item.get("f3"),
                "net_inflow": item.get("f62"),
            }
        )
    return out


def fetch_sector_fund_flow(*, indicator: str = "今日") -> list[dict[str, Any]]:
    """板块资金流排名 · indicator: 今日 / 5日 / 10日。"""
    indicator_map = {
        "今日": ("f62", "1", "f12,f14,f2,f3,f62"),
        "5日": ("f164", "5", "f12,f14,f2,f109,f164"),
        "10日": ("f174", "10", "f12,f14,f2,f160,f174"),
    }
    if indicator not in indicator_map:
        indicator = "今日"
    fid, stat, fields = indicator_map[indicator]
    data = em_get_json(
        f"{_PUSH2}/api/qt/clist/get",
        params={
            "pn": "1",
            "pz": "200",
            "po": "1",
            "np": "1",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fltt": "2",
            "invt": "2",
            "fid0": fid,
            "fs": "m:90+t:2",
            "stat": stat,
            "fields": fields,
        },
        referer="https://data.eastmoney.com/bkzj/hy.html",
    )
    if not data:
        return []
    diff = (data.get("data") or {}).get("diff") or []
    out: list[dict[str, Any]] = []
    for item in diff:
        if not isinstance(item, dict):
            continue
        net = item.get("f62") if indicator == "今日" else item.get(fid)
        out.append(
            {
                "board_code": item.get("f12"),
                "board_name": item.get("f14"),
                "pct_chg": item.get("f3") if indicator == "今日" else item.get("f109" if indicator == "5日" else "f160"),
                "net_inflow": net,
            }
        )
    return out


def fetch_a_spot_page(pn: int, *, pz: int = 100) -> tuple[list[dict[str, Any]], int | None]:
    """单页全 A 快照（push2delay · 字段精简）。"""
    data = em_get_json(
        f"{_PUSH2}/api/qt/clist/get",
        params={
            "pn": str(pn),
            "pz": str(pz),
            "po": "1",
            "np": "1",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": _SPOT_FS,
            "fields": _SPOT_FIELDS,
        },
        referer="https://quote.eastmoney.com/center/gridlist.html",
    )
    if not data:
        return [], None
    block = data.get("data") or {}
    diff = block.get("diff") or []
    total_raw = block.get("total")
    try:
        total = int(total_raw) if total_raw is not None else None
    except (TypeError, ValueError):
        total = None
    rows: list[dict[str, Any]] = []
    for item in diff:
        if not isinstance(item, dict):
            continue
        code = str(item.get("f12") or "").zfill(6)[-6:]
        if not code.isdigit():
            continue
        rows.append(
            {
                "code": code,
                "name": item.get("f14"),
                "pct_chg": item.get("f3"),
                "amount": item.get("f6"),
                "industry": item.get("f100"),
                "total_mv": item.get("f20") if item.get("f20") not in (None, "-", "") else item.get("f116"),
            }
        )
    return rows, total


def fetch_a_spot_snapshot(*, max_pages: int | None = None) -> dict[str, Any]:
    """全 A 快照 + 涨跌比/成交额（T0-1 / T0-7 共用 · 完善期禁止板块替代）。"""
    cap = int(os.environ.get("RADAR_T0_SPOT_MAX_PAGES", "60"))
    if max_pages is not None:
        cap = max_pages
    all_rows: list[dict[str, Any]] = []
    total_expected: int | None = None
    for pn in range(1, cap + 1):
        page_rows, total = fetch_a_spot_page(pn)
        if total is not None:
            total_expected = total
        if not page_rows:
            break
        all_rows.extend(page_rows)
        if total_expected and len(all_rows) >= total_expected:
            break
        _sleep_throttle()

    if not all_rows:
        return {
            "status": "error",
            "detail": "T0-1 全 A 快照不可用（东财 push2delay · 须 K3s Cron 重试至 success）",
        }

    advances = 0
    turnover = 0.0
    limit_up = 0
    for row in all_rows:
        try:
            pct = float(row.get("pct_chg") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        if pct > 0:
            advances += 1
        if pct >= 9.8:
            limit_up += 1
        try:
            turnover += float(row.get("amount") or 0)
        except (TypeError, ValueError):
            pass
    total = len(all_rows)
    from datetime import date, datetime, timezone, timedelta

    def _today_cn() -> date:
        return datetime.now(timezone(timedelta(hours=8))).date()

    return {
        "status": "ok",
        "source": "eastmoney:push2delay/spot_clist",
        "trade_date": _today_cn().isoformat(),
        "total_turnover_yi": round(turnover / 1e8, 2) if turnover else None,
        "turnover_vs_prev_pct": None,
        "advance_ratio": round(advances / total, 4) if total else None,
        "limit_up_height": limit_up,
        "advance_count": advances,
        "total_count": total,
        "row_count": total,
        "rows": all_rows,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_main_op_segments(symbol: str, *, mainop_type: str = "2") -> list[dict[str, Any]]:
    """主营构成 · datacenter RPT_F10_FN_MAINOP（按 MAINOP_TYPE 过滤）。"""
    sym = str(symbol).zfill(6)[-6:]
    payload = em_get_json(
        _DATACENTER,
        params={
            "reportName": "RPT_F10_FN_MAINOP",
            "columns": "ALL",
            "pageSize": "50",
            "pageNumber": "1",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "filter": f'(SECURITY_CODE="{sym}")',
            "source": "WEB",
            "client": "WEB",
        },
        referer=f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={'SH' if sym.startswith('6') else 'SZ'}{sym}",
    )
    if not payload:
        return []
    rows = (payload.get("result") or {}).get("data") or []
    if not rows:
        return []
    latest_date = max(str(r.get("REPORT_DATE") or "")[:10] for r in rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("MAINOP_TYPE") or "") != str(mainop_type):
            continue
        if str(row.get("REPORT_DATE") or "")[:10] != latest_date:
            continue
        name = str(row.get("ITEM_NAME") or "").strip()
        if not name or name in ("合计", "总计", "其他(补充)"):
            continue
        ratio = row.get("MBI_RATIO")
        try:
            ratio_pct = round(float(ratio) * 100, 4) if ratio is not None else None
        except (TypeError, ValueError):
            ratio_pct = None
        out.append(
            {
                "name": name,
                "revenue_ratio_pct": ratio_pct,
                "report_date": str(row.get("REPORT_DATE") or "")[:10],
                "report_name": row.get("REPORT_NAME"),
            }
        )
    out.sort(key=lambda x: x.get("revenue_ratio_pct") or 0, reverse=True)
    return out


def fetch_margin_series(symbol: str, *, lookback_days: int = 10) -> dict[str, Any] | None:
    """单标的融资融券 · 交易所日表（完善期 · 空表即 None）。"""
    sym = str(symbol).zfill(6)[-6:]
    try:
        import akshare as ak
    except ImportError:
        return None

    from datetime import datetime, timedelta

    today = datetime.now().date()
    series: list[dict[str, Any]] = []
    for offset in range(0, lookback_days + 14):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            if sym.startswith(("6", "5", "9")):
                df = ak.stock_margin_detail_sse(date=ds)
                code_col = "标的证券代码"
            else:
                df = ak.stock_margin_detail_szse(date=ds)
                code_col = "证券代码"
        except Exception:  # noqa: BLE001
            continue
        if df is None or getattr(df, "empty", True):
            continue
        if code_col not in df.columns:
            continue
        sub = df[df[code_col].astype(str).str.zfill(6) == sym]
        if sub.empty:
            continue
        r0 = sub.iloc[0]
        bal_col = "融资余额" if "融资余额" in sub.columns else None
        if bal_col is None:
            continue
        try:
            bal = float(r0[bal_col])
        except (TypeError, ValueError):
            continue
        series.append({"date": ds, "balance": bal})
        if len(series) >= lookback_days:
            break
    if not series:
        return None
    series.sort(key=lambda x: x["date"])
    roc = None
    if len(series) >= 2 and series[0]["balance"]:
        roc = round(
            (series[-1]["balance"] - series[0]["balance"]) / series[0]["balance"] * 100,
            4,
        )
    return {
        "status": "ok",
        "source": "akshare:stock_margin_detail_sse/szse",
        "latest_date": series[-1]["date"],
        "latest_balance": series[-1]["balance"],
        "balance_series": series,
        "roc_5d": roc,
    }


def fetch_board_pct_3d(board_code: str) -> float | None:
    """行业板块近 3 交易日涨跌幅（push2his · 不依赖 akshare hist）。"""
    code = str(board_code or "").strip()
    if not code:
        return None
    secid = f"90.{code}"
    data = em_get_json(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "end": "20500101",
            "lmt": "8",
        },
        referer="https://data.eastmoney.com/bkzj/hy.html",
    )
    if not data:
        return None
    klines = (data.get("data") or {}).get("klines") or []
    if len(klines) < 2:
        return None
    closes: list[float] = []
    for line in klines[-5:]:
        parts = str(line).split(",")
        if len(parts) >= 3:
            try:
                closes.append(float(parts[2]))
            except ValueError:
                continue
    if len(closes) < 2:
        return None
    last = closes[-1]
    ref = closes[-4] if len(closes) >= 4 else closes[0]
    if ref in (0, None):
        return None
    return round((last - ref) / ref * 100, 2)


def match_industry_row(rows: list[dict[str, Any]], industry: str) -> dict[str, Any] | None:
    """按行业名模糊匹配板块行（先全匹配再前缀）。"""
    ind = str(industry or "").strip()
    if not ind or not rows:
        return None
    for row in rows:
        name = str(row.get("board_name") or "")
        if name == ind or ind in name or name in ind:
            return row
    for n in (4, 3, 2):
        if len(ind) < n:
            continue
        key = ind[:n]
        for row in rows:
            name = str(row.get("board_name") or "")
            if key and key in name:
                return row
    return None


def fetch_individual_super_order_net(symbol: str, *, days: int = 5) -> dict[str, Any] | None:
    """个股超大单净流入 · push2his daykline（完善期 · 5 日合计）。"""
    import time

    sym = str(symbol).zfill(6)[-6:]
    secid = f"1.{sym}" if sym.startswith(("5", "6", "9")) else f"0.{sym}"
    params = {
        "lmt": "0",
        "klt": "101",
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "_": int(time.time() * 1000),
    }
    referer = "https://data.eastmoney.com/zjlx/detail.html"
    payload = None
    for base in (
        "https://push2his.eastmoney.com",
        _PUSH2,
        "https://push2.eastmoney.com",
    ):
        payload = em_get_json(
            f"{base.rstrip('/')}/api/qt/stock/fflow/daykline/get",
            params=dict(params, _=int(time.time() * 1000)),
            referer=referer,
            retries=4,
        )
        if payload and (payload.get("data") or {}).get("klines"):
            break
        _sleep_throttle()
    if not payload:
        return None
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return None
    tail = klines[-days:]
    nets: list[float] = []
    dates: list[str] = []
    for line in tail:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        dates.append(parts[0])
        try:
            nets.append(float(parts[5]))
        except ValueError:
            continue
    if not nets:
        return None
    return {
        "net_super_order_5d": sum(nets),
        "days": len(nets),
        "last_date": dates[-1] if dates else None,
    }


def fetch_etf_spot_rows(*, max_pages: int = 5, page_size: int = 100) -> list[dict[str, Any]]:
    """ETF 实时列表 · push2delay clist（分页）。"""
    rows: list[dict[str, Any]] = []
    for pn in range(1, max_pages + 1):
        payload = em_get_json(
            f"{_PUSH2}/api/qt/clist/get",
            params={
                "pn": str(pn),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "wbp2u": "|0|0|0|web",
                "fid": "f12",
                "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
                "fields": "f12,f14,f38,f3",
            },
            referer="https://quote.eastmoney.com/center/gridlist.html#fund_etf",
        )
        if not payload:
            break
        diff = (payload.get("data") or {}).get("diff") or []
        if not diff:
            break
        for item in diff:
            rows.append(
                {
                    "code": str(item.get("f12") or ""),
                    "name": str(item.get("f14") or ""),
                    "shares": item.get("f38"),
                    "pct_chg": item.get("f3"),
                }
            )
        if len(diff) < page_size:
            break
        _sleep_throttle()
    return rows
