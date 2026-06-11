"""巨潮 A 股财报 · 云计算分部 + 业绩会纪要 excerpt。

[Ref: 28_ §2.2 fii_odm_direct_ratio · T0 双轨侦察]
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_REPORT_TITLE = re.compile(
    r"(第一季度|一季度|半年度|第三季度|三季度|年度)报告",
    re.I,
)
_SKIP_TITLE = re.compile(r"摘要|英文|取消|更正前|修订前")
_CLOUD_SECTION = re.compile(
    r"(云计算|云端业务|云业务|服务器业务).{0,120}?(?:营业收入|收入|营收)",
    re.S,
)
_REV_WAN = re.compile(
    r"(?:营业收入|收入|营收)\s*(?:为|是|达|约)?\s*"
    r"(?P<amount>[\d,，.]+)\s*(?P<unit>万元|亿元|元|万|亿)",
)
_REV_YOY = re.compile(
    r"(?:同比|较上年同期)(?:增长|上升|增加|变动)?\s*(?P<pct>[\d.]+)\s*%",
)
_CLOUD_NARRATIVE_YOY_MULT = re.compile(
    r"云计算业务方面.{0,80}?同比增长\s*(?P<num>[\d.]+)\s*倍",
    re.S,
)
_CLOUD_NARRATIVE_YOY_PCT = re.compile(
    r"云计算业务方面.{0,80}?同比增长\s*(?P<pct>[\d.]+)\s*%",
    re.S,
)
_CLOUD_NARRATIVE_AMOUNT = re.compile(
    r"云计算业务实现营业收入\s*(?P<amount>[\d,，.]+)\s*亿元"
    r"(?:，同比增长\s*(?P<pct>[\d.]+)\s*%)?",
)
_CLOUD_TABLE_ROW = re.compile(
    r"云计算\s+(?P<curr>[\d,]+)\s+(?P<prior>[\d,]+)\s+(?P<share>[\d.]+)\s+(?P<yoy>[\d.]+)",
)
_QUARTER_TOTAL_REV = re.compile(
    r"营业收入\s+(?P<curr>[\d,]+)\s+(?P<prior>[\d,]+)",
)
_AI_SERVER = re.compile(
    r"AI\s*服务器.{0,80}?(?:营业收入|收入|占比).{0,40}?"
    r"(?P<amount>[\d,，.]+)\s*(?:%|万元|亿元|元|万|亿)",
    re.I,
)
_QA_SECTION = re.compile(
    r"(业绩说明会|投资者关系活动|问答|QA|机构调研).{0,4000}",
    re.S | re.I,
)
_ODM_DIRECT_PUBLISHED = re.compile(
    r"ODM.{0,20}?(?:直供|直接).{0,40}?(?:占比|比例)\s*(?P<pct>[\d.]+)\s*%",
    re.I,
)


def _parse_period_from_title(title: str) -> tuple[int, int, str]:
    """返回 (year, quarter 1-4, report_period 如 2026-Q1)。"""
    y = datetime.now(timezone(timedelta(hours=8))).year
    ym = re.search(r"(20\d{2})", title)
    if ym:
        y = int(ym.group(1))
    q = 4
    if "第一季" in title or "一季" in title:
        q = 1
    elif "半年" in title:
        q = 2
    elif "第三季" in title or "三季" in title:
        q = 3
    elif "年度" in title and "半年" not in title:
        q = 4
    return y, q, f"{y}-Q{q}"


def _amount_to_cny(amount_str: str, unit: str) -> float | None:
    try:
        val = float(str(amount_str).replace(",", "").replace("，", ""))
    except ValueError:
        return None
    u = unit.strip()
    if "亿" in u:
        return val * 1e8
    if "万" in u:
        return val * 1e4
    return val


def _qian_to_cny(qian_str: str) -> float:
    return float(str(qian_str).replace(",", "").replace("，", "")) * 1e3


def _find_cloud_revenue(text: str) -> tuple[float | None, float | None]:
    """(total_cloud_revenue_cny, yoy_pct)。"""
    total: float | None = None
    yoy: float | None = None

    nm = _CLOUD_NARRATIVE_AMOUNT.search(text)
    if nm:
        cny = _amount_to_cny(nm.group("amount"), "亿元")
        if cny and cny > 1e9:
            total = cny
            if nm.group("pct"):
                yoy = float(nm.group("pct"))

    if total is None:
        tm = _CLOUD_TABLE_ROW.search(text)
        if tm:
            total = _qian_to_cny(tm.group("curr"))
            try:
                yoy = float(tm.group("yoy"))
            except ValueError:
                pass

    for m in _CLOUD_SECTION.finditer(text):
        chunk = m.group(0)
        for rm in _REV_WAN.finditer(chunk):
            cny = _amount_to_cny(rm.group("amount"), rm.group("unit"))
            if cny and cny > 1e8:
                total = cny
                break
        ym = _REV_YOY.search(chunk)
        if ym:
            try:
                yoy = float(ym.group("pct"))
            except ValueError:
                pass
        if total:
            break
    if total is None:
        for rm in _REV_WAN.finditer(text):
            if "云计算" not in text[max(0, rm.start() - 80) : rm.start()]:
                continue
            cny = _amount_to_cny(rm.group("amount"), rm.group("unit"))
            if cny and cny > 1e8:
                total = cny
                break
    return total, yoy


def _parse_cloud_narrative_yoy(text: str) -> float | None:
    mm = _CLOUD_NARRATIVE_YOY_MULT.search(text)
    if mm:
        try:
            return float(mm.group("num")) * 100.0
        except ValueError:
            pass
    mp = _CLOUD_NARRATIVE_YOY_PCT.search(text)
    if mp:
        try:
            return float(mp.group("pct"))
        except ValueError:
            pass
    return None


def _parse_quarter_total_revenue_qian(text: str) -> tuple[float | None, float | None]:
    """主要财务指标表 · 营业收入（千元）→ 本季/上年同期。"""
    head = text[:4500]
    m = _QUARTER_TOTAL_REV.search(head)
    if not m:
        return None, None
    try:
        return _qian_to_cny(m.group("curr")), _qian_to_cny(m.group("prior"))
    except ValueError:
        return None, None


def _annual_cloud_anchor(symbol: str) -> dict[str, Any] | None:
    """最近一份含云计算分部金额的年报（千元表或亿元叙述）。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text, iter_cninfo_announcements

    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=550)
    best: dict[str, Any] | None = None
    best_key = ""
    for item in iter_cninfo_announcements(
        symbol,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        category="",
        keyword="",
        max_pages=8,
        throttle_sec=0.25,
    ):
        title = str(item.get("announcementTitle") or "")
        if _SKIP_TITLE.search(title):
            continue
        if "年度报告" not in title or "半年" in title:
            continue
        text = fetch_cninfo_adjunct_pdf_text(item.get("adjunctUrl"), item.get("adjunctType"))
        if not text:
            continue
        cloud_cny, yoy = _find_cloud_revenue(text)
        if cloud_cny is None:
            continue
        annual_total = None
        for m in re.finditer(r"营业收入\s+([\d,]+)\s+([\d,]+)", text[:12000]):
            annual_total = _qian_to_cny(m.group(1))
            break
        key = str(item.get("announcementTime") or title)
        if key > best_key:
            best_key = key
            best = {
                "report_title": title,
                "cloud_cny": cloud_cny,
                "cloud_yoy_pct": yoy,
                "annual_total_cny": annual_total,
            }
    return best


def _estimate_cloud_from_annual_prorate(
    quarter_text: str,
    anchor: dict[str, Any],
) -> tuple[float | None, float | None]:
    """季报无分部金额时 · 用年报云营收 × 本季/年报总营收比估算。"""
    q_total, _q_prior = _parse_quarter_total_revenue_qian(quarter_text)
    annual_total = anchor.get("annual_total_cny")
    cloud_annual = anchor.get("cloud_cny")
    if not q_total or not annual_total or not cloud_annual:
        return None, None
    if annual_total <= 0:
        return None, None
    est = float(cloud_annual) * (float(q_total) / float(annual_total))
    yoy = _parse_cloud_narrative_yoy(quarter_text) or anchor.get("cloud_yoy_pct")
    return est, yoy


def _find_ai_server(text: str) -> tuple[float | None, float | None]:
    m = _AI_SERVER.search(text)
    if not m:
        return None, None
    raw = m.group("amount")
    try:
        val = float(raw.replace(",", "").replace("，", ""))
    except ValueError:
        return None, None
    if "%" in m.group(0)[m.start() : m.end()]:
        return None, val
    return val * 1e8 if val < 1e6 else val, None


def _latest_report_item(symbol: str) -> dict[str, Any] | None:
    from apps.cryo_guard.cninfo_client import iter_cninfo_announcements

    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=450)
    best: dict[str, Any] | None = None
    best_key = ""
    for item in iter_cninfo_announcements(
        symbol,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        category="",
        keyword="",
        max_pages=6,
        throttle_sec=0.25,
    ):
        title = str(item.get("announcementTitle") or "")
        if _SKIP_TITLE.search(title):
            continue
        if not _REPORT_TITLE.search(title):
            continue
        key = str(item.get("announcementTime") or title)
        if key > best_key:
            best_key = key
            best = item
    return best


def fetch_cloud_segment_from_latest_report(symbol: str) -> dict[str, Any]:
    """解析最近一期定期报告 PDF · 云计算分部营收。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text

    sym = symbol.zfill(6)[-6:]
    item = _latest_report_item(sym)
    if not item:
        return {"ok": False, "blocker": "[A] 巨潮未找到近 15 个月定期报告"}

    title = str(item.get("announcementTitle") or "")
    text = fetch_cninfo_adjunct_pdf_text(item.get("adjunctUrl"), item.get("adjunctType"))
    if not text or len(text) < 800:
        return {"ok": False, "blocker": "[B] 定期报告 PDF 正文过短或未抽取"}

    cloud_cny, yoy = _find_cloud_revenue(text)
    source_tag = "cninfo:periodic_report_pdf"
    if cloud_cny is None:
        anchor = _annual_cloud_anchor(sym)
        if anchor:
            cloud_cny, yoy = _estimate_cloud_from_annual_prorate(text, anchor)
            if cloud_cny is not None:
                source_tag = "cninfo:periodic_report_pdf+annual_prorate"
    if cloud_cny is None:
        return {
            "ok": False,
            "blocker": "[C] PDF 未解析到云计算/云业务分部营收（需人工补 segment 表）",
            "report_title": title,
        }

    ai_cny, ai_pct = _find_ai_server(text)
    y, q, period = _parse_period_from_title(title)
    pub = _ODM_DIRECT_PUBLISHED.search(text)
    odm_pub = float(pub.group("pct")) if pub else None

    qa_m = _QA_SECTION.search(text)
    qa_excerpt = (qa_m.group(0)[:8000] if qa_m else "") or ""
    cloud_idx = text.find("云计算")
    if cloud_idx >= 0:
        report_excerpt = text[max(0, cloud_idx - 150) : cloud_idx + 5500]
    else:
        report_excerpt = text[:6000]

    return {
        "ok": True,
        "source": source_tag,
        "report_title": title,
        "report_year": y,
        "report_quarter": q,
        "report_period": period,
        "total_cloud_revenue_cny": int(cloud_cny),
        "total_cloud_yoy_pct": yoy,
        "ai_server_revenue_cny": int(ai_cny) if ai_cny else None,
        "ai_server_pct": ai_pct,
        "odm_direct_ratio_published_pct": odm_pub,
        "is_breakdown_published": odm_pub is not None,
        "qa_raw_transcript": qa_excerpt,
        "report_text_excerpt": report_excerpt,
        "pdf_chars": len(text),
    }


_SKIP_QA_TITLE = re.compile(r"关于召开|召开.*的公告|会议通知")
_PREFER_QA_TITLE = re.compile(r"投资者关系活动记录表|活动记录表")
_QA_CONTENT_MARKERS = re.compile(r"Q\d+[：:]|回复[：:]|投资者关系活动记录表")


def _qa_candidate_score(title: str, text: str) -> int:
    score = 0
    if _PREFER_QA_TITLE.search(title):
        score += 100
    if _SKIP_QA_TITLE.search(title):
        score -= 200
    if _QA_CONTENT_MARKERS.search(text):
        score += 50
    if "关于召开" in text and not _PREFER_QA_TITLE.search(title):
        score -= 40
    if len(text) >= 800:
        score += 20
    elif len(text) < 400:
        score -= 30
    return score


def fetch_qa_supplement(symbol: str) -> dict[str, Any]:
    """业绩说明会 QA 实录（优先《投资者关系活动记录表》，排除「关于召开」预告）。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text, iter_cninfo_announcements

    sym = symbol.zfill(6)[-6:]
    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=180)
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for kw in (
        "投资者关系活动",
        "活动记录表",
        "投资者关系",
        "业绩说明会",
        "调研",
        "",
    ):
        for item in iter_cninfo_announcements(
            sym,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            category="",
            keyword=kw,
            max_pages=4 if kw else 8,
            throttle_sec=0.2,
        ):
            title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or ""))
            if _SKIP_QA_TITLE.search(title):
                continue
            if kw == "" and not _PREFER_QA_TITLE.search(title):
                continue
            url = str(item.get("adjunctUrl") or "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            text = fetch_cninfo_adjunct_pdf_text(item.get("adjunctUrl"), item.get("adjunctType"))
            if not text or len(text) < 200:
                continue
            if not _QA_CONTENT_MARKERS.search(text) and not _PREFER_QA_TITLE.search(title):
                continue
            candidates.append(
                {
                    "title": title,
                    "text": text[:12000],
                    "source": f"cninfo:{kw}",
                    "score": _qa_candidate_score(title, text),
                    "adjunct_url": url,
                }
            )

    if not candidates:
        return {"ok": False, "blocker": "近 180 日无 IR 活动记录表 / QA 实录（仅预告不算）"}

    best = max(candidates, key=lambda c: int(c["score"]))
    if int(best["score"]) < 0:
        return {
            "ok": False,
            "blocker": "仅命中召开预告，无投资者关系活动记录表",
        }

    return {
        "ok": True,
        "source": best["source"],
        "report_title": best["title"],
        "qa_raw_transcript": best["text"],
        "qa_doc_score": best["score"],
        "adjunct_url": best.get("adjunct_url"),
    }

