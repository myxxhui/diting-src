"""T0-14~17 排雷域采集。

[Ref: 27_ §2.6]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call
from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_pledge_ratio


def collect_risk_bundle(sym: str) -> dict[str, Any]:
    from apps.copilot.modules.radar.scanner import _collect_financials

    fin = _collect_financials(sym)
    financial_slice = fin if fin.get("status") == "ok" else {"status": "skip", "detail": fin.get("detail")}

    return {
        "financial_slice": financial_slice,
        "pledge": _collect_pledge(sym),
        "unlock_schedule": _collect_unlock(sym),
        "regulatory_events": _collect_regulatory(sym),
    }


def _collect_pledge(sym: str) -> dict[str, Any]:
    direct = fetch_pledge_ratio(sym)
    if direct and direct.get("status") == "ok":
        return direct

    try:
        import akshare as ak
    except ImportError:
        return {"status": "error", "detail": "akshare 不可用"}

    df = ak_call(ak.stock_gpzy_pledge_ratio_detail_em)
    if df is None or df.empty:
        detail = "无质押披露表" if direct is None else "东财 datacenter 与 akshare 均不可用"
        return {"status": "skip", "detail": detail}
    code_col = "股票代码" if "股票代码" in df.columns else None
    ratio_col = "质押比例" if "质押比例" in df.columns else None
    if not code_col or not ratio_col:
        return {"status": "skip", "detail": "质押表列缺失"}
    sub = df[df[code_col].astype(str).str.zfill(6) == sym]
    if sub.empty:
        return {"status": "skip", "detail": "标的无质押记录"}
    try:
        ratio = float(str(sub.iloc[0][ratio_col]).replace("%", ""))
    except (TypeError, ValueError):
        return {"status": "error", "detail": "质押比例解析失败"}
    return {
        "status": "ok",
        "source": "akshare:stock_gpzy_pledge_ratio_detail_em",
        "pledge_ratio_pct": ratio,
    }


def _collect_unlock(sym: str) -> dict[str, Any]:
    try:
        import akshare as ak
    except ImportError:
        return {"status": "error", "detail": "akshare 不可用"}

    df = ak_call(ak.stock_restricted_release_queue_em, sym)
    if df is None or df.empty:
        df = ak_call(ak.stock_restricted_release_queue_sina, sym)
    if df is None or df.empty:
        end = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
        start = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=365)).strftime("%Y%m%d")
        df = ak_call(ak.stock_restricted_release_summary_em, symbol=sym, start_date=start, end_date=end)

    if df is None or df.empty:
        return {"status": "skip", "detail": "无解禁计划披露"}

    events: list[dict[str, Any]] = []
    for _, row in df.head(6).iterrows():
        ratio = row.get("占总市值比例")
        if ratio is None:
            ratio = row.get("解禁股流通市值")
        events.append(
            {
                "date": str(
                    row.get("解禁时间")
                    or row.get("解禁日期")
                    or row.get("限售解禁日期")
                    or ""
                ),
                "ratio_pct": ratio,
                "volume": row.get("解禁数量") or row.get("实际解禁数量"),
            }
        )
    return {
        "status": "ok",
        "source": "akshare:stock_restricted_release_queue",
        "events": events,
    }


def _collect_regulatory(sym: str) -> dict[str, Any]:
    from apps.cryo_guard.cninfo_client import iter_cninfo_announcements

    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=365)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    texts: list[str] = []
    keywords = ("问询函", "问询", "关注函", "立案调查", "立案", "警示函", "监管函")
    noise = ("募集资金专户", "三方监管协议", "存储三方")
    try:
        for kw in keywords:
            for item in iter_cninfo_announcements(
                sym,
                start_s,
                end_s,
                keyword=kw,
                max_pages=2,
                throttle_sec=0.2,
            ):
                title = str(item.get("announcementTitle") or item.get("title") or "")
                if not title or any(n in title for n in noise):
                    continue
                texts.append(f"[{kw}] {title}")
            if len(texts) >= 10:
                break
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": f"巨潮公告检索失败: {exc}"}

    if not texts:
        try:
            import akshare as ak
        except ImportError:
            return {"status": "skip", "detail": "近一年无监管类公告"}

        for cat in ("风险提示", "澄清致歉", "特别处理和退市"):
            df = ak_call(
                ak.stock_zh_a_disclosure_report_cninfo,
                symbol=sym,
                category=cat,
                start_date=start_s,
                end_date=end_s,
            )
            if df is None or df.empty:
                continue
            title_col = "公告标题" if "公告标题" in df.columns else df.columns[-1]
            for _, row in df.head(5).iterrows():
                texts.append(f"[{cat}] {row.get(title_col, '')}")

    if not texts:
        return {"status": "skip", "detail": "近一年无监管类公告"}
    deduped = list(dict.fromkeys(texts))
    out = {
        "status": "ok",
        "source": "cninfo:keyword_search",
        "events": deduped[:20],
        "raw_text": "\n".join(deduped[:10])[:8000],
    }
    from apps.copilot.modules.radar.t0.llm_enrich import enrich_regulatory_llm_tag

    return enrich_regulatory_llm_tag(out)
