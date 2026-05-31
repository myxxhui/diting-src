"""模式 C · 模糊标的深度分析 — T0 真实采集（缓存优先 + 腾讯行情链 + akshare 资料/财务）。

- **启动期**：Mac 定时 `make radar-t0-prefetch` 预拉持仓 SoT → 同步到生产 PVC；
  扫描读 `RADAR_T0_CACHE_DIR`（默认 `data/cache/radar_t0`）。
- **行情**：规约 21 · 腾讯 fqkline 优先（`fetch_bars_60d`），不直打东财 push2his。
- **资料/财务/估值**：akshare（本机预拉；生产 miss 时 live，能拿多少算多少，不全后续补）。
- **no-mock**：任一源失败返回 status=error+detail，绝不伪造 pending。

[Ref: step_14 §3.1 · 25_ §2 · 21_行情数据源]
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from apps.copilot.modules.radar.t0_cache import (
    cache_enabled,
    load_cached,
)

logger = logging.getLogger(__name__)

_T0_TIMEOUT = 15.0


def _cache_enabled() -> bool:
    return cache_enabled()


async def collect_t0_raw(
    symbol: str,
    *,
    name: str = "",
    redis_client: Any = None,  # 兼容旧签名
) -> dict[str, Any]:
    """扫描入口：优先读预拉缓存；miss 则 live 采集（腾讯行情 + 能拿到的 akshare，部分失败可接受）。"""
    sym = symbol.zfill(6)[-6:]
    if _cache_enabled():
        cached = load_cached(sym, require_fresh=True)
        if cached:
            out = {**cached, "cache_hit": True}
            if name and not out.get("name"):
                out["name"] = name
            logger.info(
                "T0 cache hit symbol=%s collected_at=%s t2=%s",
                sym,
                out.get("collected_at"),
                (cached.get("t2_verdict") or {}).get("status"),
            )
            return out
        logger.info("T0 cache miss → live 采集 symbol=%s", sym)
    return await collect_t0_live(sym, name=name)


async def collect_t0_live(symbol: str, *, name: str = "") -> dict[str, Any]:
    """强制 live 采集（预拉脚本用；不走缓存）。"""
    sym = symbol.zfill(6)[-6:]

    quote, profile, financials, valuation = await asyncio.gather(
        _safe(_collect_quote, sym),
        _safe(_collect_profile, sym),
        _safe(_collect_financials, sym),
        _safe(_collect_valuation, sym),
    )

    resolved_name = name
    if not resolved_name and profile.get("status") == "ok":
        resolved_name = profile.get("name") or sym
    resolved_name = resolved_name or sym

    return {
        "symbol": sym,
        "name": resolved_name,
        "collected_at": datetime.utcnow().isoformat(),
        "source": "live:market_quote+akshare",
        "cache_hit": False,
        "quote": quote,
        "profile": profile,
        "financials": financials,
        "valuation": valuation,
    }


async def _safe(fn, sym: str) -> dict[str, Any]:
    """统一超时 + 异常包装：失败 → status=error+detail（不伪造）。"""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, sym), timeout=_T0_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("T0 %s(%s) failed: %s", getattr(fn, "__name__", fn), sym, exc)
        return {"status": "error", "detail": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _pct(cur: float, prev: float) -> float | None:
    if prev in (0, None) or cur is None:
        return None
    return round((cur - prev) / prev * 100, 2)


def _collect_quote(sym: str) -> dict[str, Any]:
    """近 60 日日 K（规约 21：腾讯 fqkline → 新浪 → 东财末级），算多周期涨跌幅与量比。"""
    from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_60d

    bars = fetch_bars_60d(sym)
    if not bars or len(bars) < 6:
        return {"status": "error", "detail": "行情数据不足（腾讯/新浪/东财均不可用）"}
    closes = [float(b.close) for b in bars]
    vols = [float(b.volume) for b in bars]
    last = closes[-1]

    def _back(n: int) -> float | None:
        return _pct(last, closes[-1 - n]) if len(closes) > n else None

    vol_ratio_5d = None
    if len(vols) >= 6:
        prev5 = sum(vols[-6:-1]) / 5
        vol_ratio_5d = round(vols[-1] / prev5, 2) if prev5 else None

    return {
        "status": "ok",
        "source": "market_quote",
        "last_close": round(last, 2),
        "pct_chg_1d": _back(1),
        "pct_chg_5d": _back(5),
        "pct_chg_20d": _back(20),
        "pct_chg_60d": _back(min(59, len(closes) - 1)),
        "volume_ratio_5d": vol_ratio_5d,
        "bars": len(closes),
        "as_of": str(bars[-1].date),
    }


def _collect_profile(sym: str) -> dict[str, Any]:
    """公司资料：行业/简称/总市值/流通市值/上市时间。"""
    import akshare as ak

    df = ak.stock_individual_info_em(symbol=sym)
    if df is None or df.empty:
        return {"status": "error", "detail": "未取到公司资料"}
    info = dict(zip(df["item"].astype(str), df["value"]))

    def _mv(v: Any) -> float | None:
        try:
            return round(float(v) / 1e8, 2)  # 元 → 亿元
        except (TypeError, ValueError):
            return None

    return {
        "status": "ok",
        "name": str(info.get("股票简称") or "").strip() or sym,
        "industry": str(info.get("行业") or "").strip() or None,
        "total_mv_yi": _mv(info.get("总市值")),
        "float_mv_yi": _mv(info.get("流通市值")),
        "listing_date": str(info.get("上市时间") or "").strip() or None,
    }


_FIN_PICK = {
    "营业总收入": "revenue",
    "归母净利润": "net_profit_parent",
    "净利润": "net_profit",
    "销售毛利率": "gross_margin",
    "净资产收益率(ROE)": "roe",
    "净资产收益率": "roe",
    "资产负债率": "debt_ratio",
    "营业总收入同比增长": "revenue_yoy",
    "归母净利润同比增长": "net_profit_yoy",
    "经营现金流量净额": "operating_cashflow",
}


def _collect_financials(sym: str) -> dict[str, Any]:
    """财务摘要：营收/净利/毛利率/ROE/负债率/同比 + 最近报告期。"""
    import akshare as ak

    df = ak.stock_financial_abstract(symbol=sym)
    if df is None or df.empty or "指标" not in df.columns:
        return {"status": "error", "detail": "未取到财务摘要"}
    date_cols = [c for c in df.columns if str(c)[:4].isdigit()]
    if not date_cols:
        return {"status": "error", "detail": "财务摘要无报告期列"}
    latest = sorted(date_cols, reverse=True)[0]

    picked: dict[str, Any] = {}
    for _, r in df.iterrows():
        ind = str(r["指标"]).strip()
        for zh, en in _FIN_PICK.items():
            if ind == zh and en not in picked:
                v = r.get(latest)
                try:
                    picked[en] = round(float(v), 4)
                except (TypeError, ValueError):
                    picked[en] = v if v is not None else None
    if not picked:
        return {"status": "error", "detail": "财务摘要无可用指标"}
    return {"status": "ok", "report_period": str(latest), **picked}


def _collect_valuation(sym: str) -> dict[str, Any]:
    """估值分位：乐咕 PE/PB 历史序列 → 当前 PE-TTM 及其历史百分位。"""
    import akshare as ak

    df = ak.stock_a_indicator_lg(symbol=sym)
    if df is None or df.empty:
        return {"status": "error", "detail": "未取到估值序列"}
    col = "pe_ttm" if "pe_ttm" in df.columns else ("pe" if "pe" in df.columns else None)
    if col is None:
        return {"status": "error", "detail": "估值序列无 PE 列"}
    series = df[col].dropna().astype(float)
    series = series[series > 0]
    if series.empty:
        return {"status": "error", "detail": "PE 序列无有效正值"}
    cur = float(series.iloc[-1])
    pct_rank = round(float((series <= cur).mean()) * 100, 1)
    pb_cur = None
    if "pb" in df.columns:
        pb = df["pb"].dropna().astype(float)
        if not pb.empty:
            pb_cur = round(float(pb.iloc[-1]), 2)
    return {
        "status": "ok",
        "pe_ttm": round(cur, 2),
        "pe_percentile": pct_rank,
        "pb": pb_cur,
        "history_points": int(series.shape[0]),
        "as_of": str(df["trade_date"].iloc[-1]) if "trade_date" in df.columns else None,
    }


def t1_to_candidate_fields(
    t0: dict[str, Any], t1: dict[str, Any], t2: dict[str, Any]
) -> dict[str, Any]:
    """从 Opus 9 维 verdict 映射 radar_candidates 列 + 存全量 deep_analysis + 成本。"""
    profile = t0.get("profile") or {}
    valuation = t0.get("valuation") or {}
    deep = t2.get("deep_analysis") or {}
    dims = deep.get("dimensions") or {}
    overall = deep.get("overall") or {}

    def _vd(key: str) -> Any:
        return (dims.get(key) or {}).get("verdict")

    t2_ok = t2.get("status") == "ok"
    confidence = float(overall.get("confidence") or t2.get("confidence") or 0.0)

    return {
        "symbol": t0.get("symbol"),
        "name": t0.get("name") or t0.get("symbol"),
        "industry": profile.get("industry") if profile.get("status") == "ok" else None,
        "niche_text": _vd("niche") if t2_ok else None,
        "value_chain_pos": _vd("value_chain") if t2_ok else None,
        "is_leader": _vd("is_leader") if t2_ok else None,
        "leader_confidence": (dims.get("is_leader") or {}).get("confidence") if t2_ok else None,
        "moat_level": _vd("moat") if t2_ok else None,
        "profit_quality": _vd("profit_quality") if t2_ok else None,
        "market_phase": _vd("market_phase") if t2_ok else None,
        "catalyst_window": _catalyst_window(dims) if t2_ok else None,
        "risk_summary": _vd("risk") if t2_ok else (t2.get("detail") if not t2_ok else None),
        "confidence": confidence,
        "evidence_ref": f"scan:{t0.get('symbol')}",
        "raw_json": {
            "deep_analysis": deep,
            "t2_status": t2.get("status"),
            "t2_detail": t2.get("detail"),
            "cost": {
                "model": t2.get("model_id"),
                "route": t2.get("route"),
                "tokens_in": t2.get("tokens_in", 0),
                "tokens_out": t2.get("tokens_out", 0),
                "cost_yuan": t2.get("cost_yuan", 0.0),
            },
            "valuation_pe_percentile": valuation.get("pe_percentile")
            if valuation.get("status") == "ok"
            else None,
        },
    }


def _catalyst_window(dims: dict[str, Any]) -> str | None:
    items = (dims.get("catalyst_timeline") or {}).get("items") or []
    if items and isinstance(items[0], dict):
        return items[0].get("window")
    return (dims.get("catalyst_timeline") or {}).get("verdict")
