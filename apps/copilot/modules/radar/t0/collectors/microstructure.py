"""T0 域 3 微观结构采集（T0-8~11）。

[Ref: 27_ §2.4]
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LIMIT_UP_PCT = 9.8  # A 股涨停近似阈值（ST 除外 · 启动期简化）
_AK_TIMEOUT = float(os.environ.get("RADAR_T0_AKSHARE_TIMEOUT_SEC", "12"))


def _ak_call(fn, *args, **kwargs):
    """akshare 调用硬超时，避免 margin/lhb 全表拖死扫描。"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=_AK_TIMEOUT)
        except FuturesTimeout:
            logger.warning("akshare 超时 %ss: %s", _AK_TIMEOUT, getattr(fn, "__name__", fn))
            return None


def _cache_dir() -> Path:
    base = Path(os.environ.get("RADAR_T0_CACHE_DIR", "data/cache/radar_t0"))
    micro = base / "micro"
    micro.mkdir(parents=True, exist_ok=True)
    return micro


def _bars_to_summary(bars: list[Any], *, source: str, sym: str) -> dict[str, Any]:
    """由 Bar 或 dict 列表计算 T0-8 摘要 + 持久化 JSON。"""
    if not bars:
        return {"status": "error", "detail": "无 K 线数据"}

    rows: list[dict[str, Any]] = []
    closes: list[float] = []
    for b in bars:
        if hasattr(b, "close"):
            c = float(b.close)
            rows.append(
                {
                    "date": str(getattr(b, "date", "")),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": c,
                    "volume": float(b.volume),
                }
            )
        elif isinstance(b, dict):
            c = float(b.get("close") or 0)
            rows.append(
                {
                    "date": str(b.get("date") or ""),
                    "open": float(b.get("open") or 0),
                    "high": float(b.get("high") or 0),
                    "low": float(b.get("low") or 0),
                    "close": c,
                    "volume": float(b.get("volume") or 0),
                }
            )
        else:
            continue
        closes.append(c)

    if len(closes) < 20:
        return {"status": "error", "detail": f"K 线不足 {len(closes)} 根（需≥20）"}

    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    last = closes[-1]

    limit_up_20d = 0
    for i in range(max(1, len(closes) - 20), len(closes)):
        prev = closes[i - 1]
        if prev > 0 and (closes[i] - prev) / prev * 100 >= _LIMIT_UP_PCT:
            limit_up_20d += 1

    cache_path: str | None = None
    path = _cache_dir() / f"{sym}_bars250.json"
    try:
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        cache_path = str(path)
    except OSError as exc:
        logger.warning("bars250 缓存写入失败: %s", exc)

    tag_side = "右侧" if last >= ma20 else "左侧"
    if ma60 and last >= ma20 >= ma60:
        tag_side = "多头排列"
    elif ma60 and last < ma20 < ma60:
        tag_side = "空头排列"

    return {
        "status": "ok",
        "source": source,
        "bars_count": len(closes),
        "as_of": rows[-1].get("date") if rows else None,
        "cache_path": cache_path,
        "summary": {
            "last_close": round(last, 4),
            "ma20": round(ma20, 4),
            "ma60": round(ma60, 4) if ma60 else None,
            "above_ma20": last >= ma20,
            "limit_up_count_20d": limit_up_20d,
            "side_tag": tag_side,
        },
    }


def collect_bars_250d(sym: str) -> dict[str, Any]:
    """T0-8 · 250 日 OHLCV：QMT 桥 → MarketQuote → akshare。"""
    from apps.copilot.modules.radar.t0.qmt_bridge_client import QmtBridgeClient
    from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_250d

    qmt = QmtBridgeClient()
    raw: list[Any] | None = None
    source = "market_quote"

    if qmt.enabled():
        qmt_rows = qmt.fetch_kline(sym, days=250)
        if qmt_rows:
            raw = qmt_rows
            source = "qmt_bridge"

    if raw is None:
        bars = fetch_bars_250d(sym)
        if bars:
            raw = bars
            source = "market_quote" if len(bars) >= 200 else "market_quote_partial"

    if raw is None:
        return {"status": "error", "detail": "T0-8 250日K线全源失败"}

    return _bars_to_summary(raw, source=source, sym=sym)


def collect_northbound(sym: str) -> dict[str, Any]:
    """T0-9 · 陆股通持股与近 30 日增减持（akshare）。"""
    try:
        import akshare as ak
    except ImportError:
        return {"status": "error", "detail": "akshare 不可用"}

    try:
        df = _ak_call(ak.stock_hsgt_individual_em, symbol=sym)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": f"北向持股接口失败: {str(exc)[:120]}"}

    if df is None or df.empty:
        return {"status": "skip", "detail": "标的非陆股通成分或无北向披露"}

    tail = df.tail(30)
    net_col = "今日增持资金" if "今日增持资金" in tail.columns else None
    if net_col is None:
        return {"status": "error", "detail": "北向数据列缺失"}

    series = [float(x or 0) for x in tail[net_col].tolist()]
    net_5d_yi = round(sum(series[-5:]) / 1e8, 4) if len(series) >= 5 else None
    net_30d_yi = round(sum(series) / 1e8, 4)

    return {
        "status": "ok",
        "source": "akshare:stock_hsgt_individual_em",
        "net_buy_5d_yi": net_5d_yi,
        "net_buy_30d_yi": net_30d_yi,
        "daily_net_buy_yi": [round(v / 1e8, 4) for v in series],
        "as_of": str(tail.iloc[-1].get("持股日期", "")),
    }


def _sse_sym(sym: str) -> bool:
    return sym.startswith(("6", "5", "9"))


def collect_margin(sym: str) -> dict[str, Any]:
    """T0-10 · 融资余额 ROC（交易所日表 · datacenter/akshare · 完善期须真实采集）。"""
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_margin_series

    direct = fetch_margin_series(sym)
    if direct and direct.get("status") == "ok":
        return direct

    try:
        import akshare as ak
    except ImportError:
        return {"status": "error", "detail": "akshare 不可用"}

    today = datetime.utcnow().date()
    for offset in range(0, 10):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            if _sse_sym(sym):
                df = _ak_call(ak.stock_margin_detail_sse, date=ds)
                code_col = "标的证券代码"
            else:
                df = _ak_call(ak.stock_margin_detail_szse, date=ds)
                code_col = "证券代码"
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            if "Length mismatch" in err or "empty" in err.lower():
                continue
            return {"status": "error", "detail": f"融资接口异常: {err[:80]}"}
        if df is None:
            continue
        if getattr(df, "empty", True) or code_col not in getattr(df, "columns", []):
            continue
        sub = df[df[code_col].astype(str).str.zfill(6) == sym]
        if sub.empty:
            continue
        bal_col = "融资余额" if "融资余额" in sub.columns else None
        if bal_col is None:
            continue
        bal = float(sub.iloc[0][bal_col])
        return {
            "status": "ok",
            "source": "akshare:stock_margin_detail_sse/szse",
            "latest_date": ds,
            "latest_balance": bal,
            "balance_series": [{"date": ds, "balance": bal}],
            "roc_5d": None,
        }
    return {"status": "skip", "detail": "融资融券日表无该标的"}


def collect_dragon_tiger(sym: str, *, max_days: int = 3) -> dict[str, Any]:
    """T0-11 · 近若干日龙虎榜明细聚合（启动期限 3 日 × 买入明细，控时）。"""
    try:
        import akshare as ak
    except ImportError:
        return {"status": "error", "detail": "akshare 不可用"}

    try:
        dates_df = _ak_call(ak.stock_lhb_stock_detail_date_em, symbol=sym)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": f"龙虎榜日期接口失败: {str(exc)[:120]}"}

    if dates_df is None or dates_df.empty:
        return {"status": "skip", "detail": "近 10 日无龙虎榜上榜记录"}

    date_col = "交易日" if "交易日" in dates_df.columns else dates_df.columns[-1]
    appearance = len(dates_df.head(10))
    entries: list[dict[str, Any]] = []
    inst_net = 0.0
    hot_net = 0.0

    for _, row in dates_df.head(max_days).iterrows():
        trade_day = str(row[date_col]).replace("-", "")[:8]
        det = _ak_call(ak.stock_lhb_stock_detail_em, symbol=sym, date=trade_day, flag="买入")
        if det is None or det.empty:
            continue
        for _, r in det.iterrows():
            seat = str(r.get("营业部名称") or r.get("交易营业部名称") or "")
            net = float(r.get("净额") or r.get("买入金额") or 0)
            entries.append({"date": trade_day, "seat": seat, "flag": "买入", "net": net})
            if "机构专用" in seat:
                inst_net += net
            elif any(k in seat for k in ("拉萨", "东方财富", "华泰", "中信", "国泰君安")):
                hot_net += net

    if not entries and appearance == 0:
        return {"status": "skip", "detail": "近 10 日无龙虎榜上榜记录"}

    return {
        "status": "ok",
        "source": "akshare:stock_lhb_stock_detail_em",
        "appearance_count": appearance,
        "entries": entries[:80],
        "institution_net": round(inst_net, 2),
        "hot_money_net": round(hot_net, 2),
    }


def collect_microstructure(sym: str) -> dict[str, Any]:
    """并行调用四个微观 collector，写入 ``micro`` 子树。"""
    from concurrent.futures import ThreadPoolExecutor

    tasks = {
        "bars_250d": lambda: collect_bars_250d(sym),
        "northbound": lambda: collect_northbound(sym),
        "margin": lambda: collect_margin(sym),
        "dragon_tiger": lambda: collect_dragon_tiger(sym),
    }
    out: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fn): key for key, fn in tasks.items()}
        for fut in futs:
            key = futs[fut]
            try:
                out[key] = fut.result(timeout=_AK_TIMEOUT + 15)
            except Exception as exc:  # noqa: BLE001
                out[key] = {"status": "error", "detail": str(exc)[:120]}
    return out
