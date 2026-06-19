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
from collections.abc import Callable
from typing import Any

from apps.copilot.modules.radar.t0_cache import (
    cache_enabled,
    load_cached,
)

logger = logging.getLogger(__name__)

_T0_TIMEOUT = 35.0
_MICRO_TIMEOUT = 45.0


def _cache_enabled() -> bool:
    return cache_enabled()


async def collect_t0_raw(
    symbol: str,
    *,
    name: str = "",
    redis_client: Any = None,  # 兼容旧签名
    force_refresh: bool = False,
) -> dict[str, Any]:
    """扫描入口：优先读预拉缓存；miss 或 force_refresh 则 live 采集。"""
    sym = symbol.zfill(6)[-6:]
    if force_refresh:
        logger.info("T0 force_refresh → live 采集 symbol=%s", sym)
        return await collect_t0_live(sym, name=name)
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


async def collect_t0_live(
    symbol: str,
    *,
    name: str = "",
    on_step: Callable[[str, str, int | None, str], None] | None = None,
) -> dict[str, Any]:
    """强制 live 采集（预拉脚本用；不走缓存）。on_step(step_id, label, pct, detail) 可选。"""
    sym = symbol.zfill(6)[-6:]

    _steps: list[tuple[str, str, Any, int]] = [
        ("quote", "行情 K 线", _collect_quote, 28),
        ("profile", "公司资料", _collect_profile, 45),
        ("financials", "财务摘要", _collect_financials, 62),
        ("valuation", "估值分位", _collect_valuation, 78),
        ("micro", "微观结构", _collect_micro, 92),
    ]
    quote: dict[str, Any]
    profile: dict[str, Any]
    financials: dict[str, Any]
    valuation: dict[str, Any]
    micro: dict[str, Any]

    if on_step is None:
        quote, profile, financials, valuation, micro = await asyncio.gather(
            _safe(_collect_quote, sym),
            _safe(_collect_profile, sym),
            _safe(_collect_financials, sym),
            _safe(_collect_valuation, sym),
            _safe_micro(sym),
        )
    else:
        quote = profile = financials = valuation = micro = {"status": "pending"}
        for step_id, label, fn, pct in _steps:
            on_step(step_id, label, pct, f"正在拉取 {label}…")
            if step_id == "micro":
                part = await _safe_micro(sym)
            else:
                part = await _safe(fn, sym)
            st = part.get("status", "?") if step_id != "micro" else _micro_status(part)
            if step_id == "quote":
                quote = part
            elif step_id == "profile":
                profile = part
            elif step_id == "financials":
                financials = part
            elif step_id == "valuation":
                valuation = part
            else:
                micro = part
            on_step(step_id, label, pct, f"{label}：{st}")

    resolved_name = name
    if not resolved_name and profile.get("status") == "ok":
        resolved_name = profile.get("name") or sym
    resolved_name = resolved_name or sym

    domains = await _safe_domains(sym)
    macro_snap = domains.get("macro", {}).get("market_sentiment")
    out = {
        "symbol": sym,
        "name": resolved_name,
        "collected_at": datetime.utcnow().isoformat(),
        "source": "live:market_quote+akshare",
        "cache_hit": False,
        "quote": quote,
        "profile": profile,
        "financials": financials,
        "valuation": valuation,
        "micro": domains.get("micro") or micro,
    }
    for key in ("macro", "ecosystem", "consensus", "risk"):
        if domains.get(key):
            out[key] = domains[key]
    eco_prof = (domains.get("ecosystem") or {}).get("profile")
    if isinstance(eco_prof, dict) and eco_prof.get("status") == "ok":
        out["profile"] = eco_prof
    reg = (domains.get("risk") or {}).get("regulatory_events")
    if isinstance(reg, dict) and reg.get("status") == "ok":
        out.setdefault("risk", {})["regulatory_events"] = reg
    if macro_snap and macro_snap.get("status") == "ok":
        out.setdefault("macro", {})["market_sentiment"] = macro_snap
    return out


async def _safe_domains(sym: str) -> dict[str, Any]:
    try:
        from apps.copilot.db.database import AsyncSessionLocal
        from apps.copilot.modules.radar.t0.collectors.market_sentiment import load_macro_for_scan_async
        from apps.copilot.modules.radar.t0.collectors.symbol_bundle import collect_symbol_domains
        from apps.copilot.services.redis_wait import wait_for_sync_redis

        redis_client = wait_for_sync_redis()
        async with AsyncSessionLocal() as session:
            macro = await load_macro_for_scan_async(session, redis_client)
        return await asyncio.wait_for(
            asyncio.to_thread(collect_symbol_domains, sym, macro_snapshot=macro),
            timeout=120.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("T0 domains(%s) failed: %s", sym, exc)
        return {}


def _micro_status(micro: dict[str, Any]) -> str:
    ok = sum(
        1
        for k in ("bars_250d", "northbound", "margin", "dragon_tiger")
        if (micro.get(k) or {}).get("status") == "ok"
    )
    skip = sum(
        1
        for k in ("bars_250d", "northbound", "margin", "dragon_tiger")
        if (micro.get(k) or {}).get("status") == "skip"
    )
    return f"ok={ok}/skip={skip}"


def _collect_micro(sym: str) -> dict[str, Any]:
    from apps.copilot.modules.radar.t0.collectors.microstructure import collect_microstructure

    return collect_microstructure(sym)


async def _safe_micro(sym: str) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_collect_micro, sym), timeout=_MICRO_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("T0 micro(%s) failed: %s", sym, exc)
        err = {"status": "error", "detail": f"{type(exc).__name__}: {str(exc)[:160]}"}
        return {
            "bars_250d": err,
            "northbound": err,
            "margin": err,
            "dragon_tiger": err,
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


def _mv_yi(v: Any) -> float | None:
    try:
        return round(float(v) / 1e8, 2)
    except (TypeError, ValueError):
        return None


def _collect_profile_em(sym: str) -> dict[str, Any]:
    import akshare as ak

    df = ak.stock_individual_info_em(symbol=sym)
    if df is None or df.empty:
        return {"status": "error", "detail": "未取到公司资料(em)"}
    info = dict(zip(df["item"].astype(str), df["value"]))
    return {
        "status": "ok",
        "source": "akshare:stock_individual_info_em",
        "name": str(info.get("股票简称") or "").strip() or sym,
        "industry": str(info.get("行业") or "").strip() or None,
        "total_mv_yi": _mv_yi(info.get("总市值")),
        "float_mv_yi": _mv_yi(info.get("流通市值")),
        "listing_date": str(info.get("上市时间") or "").strip() or None,
    }


def _latest_value_em(sym: str) -> dict[str, Any] | None:
    """东财估值表末行：市值 + PE/PB（profile/valuation 共用）。"""
    import akshare as ak

    df = ak.stock_value_em(symbol=sym)
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    return {
        "as_of": str(row.get("数据日期") or "").strip() or None,
        "total_mv_yi": _mv_yi(row.get("总市值")),
        "float_mv_yi": _mv_yi(row.get("流通市值")),
        "pe_ttm": _safe_float(row.get("PE(TTM)")),
        "pb": _safe_float(row.get("市净率")),
        "pe_series": df["PE(TTM)"].dropna().astype(float),
    }


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return round(f, 4) if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def _collect_profile_cninfo(sym: str) -> dict[str, Any]:
    import akshare as ak

    df = ak.stock_profile_cninfo(symbol=sym)
    if df is None or df.empty:
        return {"status": "error", "detail": "未取到公司资料(cninfo)"}
    row = df.iloc[0]
    em = _latest_value_em(sym)
    listing = str(row.get("上市日期") or "").strip() or None
    if listing and len(listing) >= 10:
        listing = listing.replace("-", "")[:8]
    return {
        "status": "ok",
        "source": "akshare:stock_profile_cninfo+stock_value_em",
        "name": str(row.get("A股简称") or row.get("公司名称") or sym).strip() or sym,
        "industry": str(row.get("所属行业") or "").strip() or None,
        "total_mv_yi": (em or {}).get("total_mv_yi"),
        "float_mv_yi": (em or {}).get("float_mv_yi"),
        "listing_date": listing,
    }


def _collect_profile(sym: str) -> dict[str, Any]:
    """公司资料：东财 em 优先；失败走 cninfo + 东财估值表补市值。"""
    try:
        out = _collect_profile_em(sym)
        if out.get("status") == "ok":
            return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("profile em failed %s: %s", sym, exc)
    try:
        return _collect_profile_cninfo(sym)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": f"profile 全源失败: {type(exc).__name__}: {str(exc)[:120]}"}


_FIN_PICK = {
    "营业总收入": "revenue",
    "归母净利润": "net_profit_parent",
    "净利润": "net_profit",
    "销售毛利率": "gross_margin",
    "毛利率": "gross_margin",
    "净资产收益率(ROE)": "roe",
    "净资产收益率": "roe",
    "资产负债率": "debt_ratio",
    "营业总收入同比增长": "revenue_yoy",
    "归母净利润同比增长": "net_profit_yoy",
    "经营现金流量净额": "operating_cashflow",
}


def _parse_pct(v: Any) -> float | None:
    if v is None or v is False:
        return None
    s = str(v).strip().replace("%", "")
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def _supplement_financials_yoy(sym: str, picked: dict[str, Any]) -> None:
    """同花顺摘要补同比（东财 abstract 常缺）。"""
    if picked.get("revenue_yoy") is not None and picked.get("net_profit_yoy") is not None:
        return
    import akshare as ak

    df = ak.stock_financial_abstract_ths(symbol=sym, indicator="按报告期")
    if df is None or df.empty:
        return
    row = df.iloc[-1]
    if picked.get("revenue_yoy") is None:
        picked["revenue_yoy"] = _parse_pct(row.get("营业总收入同比增长率"))
    if picked.get("net_profit_yoy") is None:
        picked["net_profit_yoy"] = _parse_pct(row.get("净利润同比增长率"))


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
    _supplement_financials_yoy(sym, picked)
    return {"status": "ok", "source": "akshare:stock_financial_abstract", "report_period": str(latest), **picked}


def _pe_percentile(series) -> tuple[float, float] | None:
    import pandas as pd

    s = pd.Series(series).dropna().astype(float)
    s = s[s > 0]
    if s.empty:
        return None
    cur = float(s.iloc[-1])
    pct = round(float((s <= cur).mean()) * 100, 1)
    return cur, pct


def _collect_valuation_lg(sym: str) -> dict[str, Any]:
    import akshare as ak

    df = ak.stock_a_indicator_lg(symbol=sym)
    if df is None or df.empty:
        return {"status": "error", "detail": "未取到估值序列(lg)"}
    col = "pe_ttm" if "pe_ttm" in df.columns else ("pe" if "pe" in df.columns else None)
    if col is None:
        return {"status": "error", "detail": "估值序列无 PE 列"}
    ranked = _pe_percentile(df[col])
    if ranked is None:
        return {"status": "error", "detail": "PE 序列无有效正值"}
    cur, pct_rank = ranked
    pb_cur = None
    if "pb" in df.columns:
        pb = df["pb"].dropna().astype(float)
        if not pb.empty:
            pb_cur = round(float(pb.iloc[-1]), 2)
    return {
        "status": "ok",
        "source": "akshare:stock_a_indicator_lg",
        "pe_ttm": round(cur, 2),
        "pe_percentile": pct_rank,
        "pb": pb_cur,
        "history_points": int(df[col].dropna().shape[0]),
        "as_of": str(df["trade_date"].iloc[-1]) if "trade_date" in df.columns else None,
    }


def _collect_valuation_em(sym: str) -> dict[str, Any]:
    em = _latest_value_em(sym)
    if not em or em.get("pe_ttm") is None:
        return {"status": "error", "detail": "未取到估值序列(value_em)"}
    ranked = _pe_percentile(em["pe_series"])
    if ranked is None:
        return {"status": "error", "detail": "PE 序列无有效正值(value_em)"}
    cur, pct_rank = ranked
    return {
        "status": "ok",
        "source": "akshare:stock_value_em",
        "pe_ttm": round(cur, 2),
        "pe_percentile": pct_rank,
        "pb": em.get("pb"),
        "history_points": int(em["pe_series"].dropna().shape[0]),
        "as_of": em.get("as_of"),
    }


def _collect_valuation(sym: str) -> dict[str, Any]:
    """估值分位：乐咕 lg 优先；失败走东财 stock_value_em 历史 PE(TTM) 分位。"""
    try:
        out = _collect_valuation_lg(sym)
        if out.get("status") == "ok":
            return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("valuation lg failed %s: %s", sym, exc)
    try:
        return _collect_valuation_em(sym)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": f"valuation 全源失败: {type(exc).__name__}: {str(exc)[:120]}"}


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

    # 防御性截断：Opus 有时不遵守 {yes|no|inferred} 等枚举约束，返回长句
    def _v32(key: str) -> str | None:
        v = _vd(key)
        if isinstance(v, str) and len(v) > 32:
            _log_varchar_trunc(key, v)
            return v[:32]
        return v

    return {
        "symbol": t0.get("symbol"),
        "name": t0.get("name") or t0.get("symbol"),
        "industry": profile.get("industry") if profile.get("status") == "ok" else None,
        "niche_text": _vd("niche") if t2_ok else None,
        "value_chain_pos": _vd("value_chain") if t2_ok else None,
        "is_leader": _v32("is_leader") if t2_ok else None,
        "leader_confidence": (dims.get("is_leader") or {}).get("confidence") if t2_ok else None,
        "moat_level": _v32("moat") if t2_ok else None,
        "profit_quality": _v32("profit_quality") if t2_ok else None,
        "market_phase": _v32("market_phase") if t2_ok else None,
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


def _log_varchar_trunc(field: str, value: str) -> None:
    """LLM 输出超出 VARCHAR(32) 时记录截断日志，不打断流程。"""
    import logging
    _logger = logging.getLogger("radar.scanner")
    _logger.warning(
        "radar_candidates.%s verdict too long (%d chars), truncating to 32. "
        "Original: %s...",
        field, len(value), value[:120],
    )
