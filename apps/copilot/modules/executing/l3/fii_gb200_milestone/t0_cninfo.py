"""巨潮 · GB200/智算机柜里程碑公告 + IR 实录。

[Ref: 28_ §2.2 fii_gb200_milestone · T0 Sensor Layer]
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    ANNOUNCEMENT_KEYWORDS,
    event_window_meta,
    event_window_start,
    is_within_event_window,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))
_SKIP_TITLE = re.compile(r"取消|更正前|修订前|提示性|停牌")
_IRRELEVANT_TITLE = re.compile(
    r"回购|减持|股份变动|股权激励|员工持股|理财|担保|关联交易|利润分配|分红"
)
_PERIODIC_REPORT_TITLE = re.compile(r"年度报告|半年度报告|季度报告|第一季度|第三季度")
_MEETING_NOTICE_TITLE = re.compile(r"关于召开|召开.*说明会|会议通知")
_PREFER_TITLE = re.compile(
    r"自愿性信息|投资者关系|活动记录|调研|说明会|进展|交付|量产|GB200|NVL|智算|机柜",
    re.I,
)


def _parse_pub_date(item: dict[str, Any]) -> str | None:
    def _valid(d: str) -> bool:
        try:
            parsed = datetime.strptime(d[:10], "%Y-%m-%d")
            return 2000 <= parsed.year <= 2035
        except ValueError:
            return False

    raw = item.get("announcementTime") or ""
    s = str(raw).strip()
    if len(s) >= 10 and s[4] == "-":
        d = s[:10]
        if _valid(d):
            return d
    if len(s) >= 8 and s[:8].isdigit():
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if _valid(d):
            return d
    url = str(item.get("adjunctUrl") or "")
    m = re.search(r"/(\d{4}-\d{2}-\d{2})/", url)
    if m and _valid(m.group(1)):
        return m.group(1)
    m2 = re.search(r"/(\d{4})(\d{2})(\d{2})/", url)
    if m2:
        d = f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
        if _valid(d):
            return d
    return None


def _score_announcement(title: str, text: str) -> int:
    blob = f"{title}\n{text}"
    score = 0
    if _PREFER_TITLE.search(title):
        score += 40
    if _SKIP_TITLE.search(title):
        score -= 80
    if _IRRELEVANT_TITLE.search(title) and not re.search(
        r"GB200|NVL|智算|机柜|Blackwell|规模交付|量产|AI服务器", title, re.I
    ):
        score -= 120
    if _PERIODIC_REPORT_TITLE.search(title) and not re.search(
        r"GB200|NVL|智算|机柜|Blackwell|规模交付", title, re.I
    ):
        score -= 70
    if _MEETING_NOTICE_TITLE.search(title) and not re.search(
        r"GB200|NVL|智算|机柜|Blackwell|规模交付|量产", title, re.I
    ):
        score -= 80
    for kw in ANNOUNCEMENT_KEYWORDS:
        if kw in blob:
            score += 12 if kw in ("GB200", "NVL72", "NVL36") else 8
    if "规模交付" in blob or "量产" in blob:
        score += 25
    if len(text) >= 400:
        score += 15
    elif len(text) >= 120:
        score += 5
    return score


_GB200_MILESTONE_MARKERS = re.compile(
    r"GB200|NVL72|NVL36|智算机柜|Blackwell",
    re.I,
)


def _body_has_gb200_signal(text: str) -> bool:
    """排除年报中 NVLinkSwitch 等泛 NVL 误命中。"""
    return bool(_GB200_MILESTONE_MARKERS.search(text or ""))


def _candidate_rank_key(c: dict[str, Any]) -> tuple[int, int, int, str]:
    title = str(c.get("title") or "")
    body = str(c.get("text") or "")
    gb200_hit = 1 if re.search(r"GB200", body, re.I) else 0
    full_report = 0 if "摘要" in title else 1
    return (int(c.get("score") or 0), gb200_hit, full_report, str(c.get("published_date") or ""))


def _rescore_candidates_with_pdf(
    candidates: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """对标题分偏低的条目拉 PDF 正文重评分（业绩会实录常在正文而非标题）。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text

    ranked = sorted(candidates, key=lambda c: (int(c["score"]), str(c.get("published_date") or "")), reverse=True)
    out: list[dict[str, Any]] = []
    for cand in ranked[:limit]:
        row = dict(cand)
        url = str(row.get("adjunct_url") or "")
        body = ""
        if url:
            try:
                body = fetch_cninfo_adjunct_pdf_text(row.get("adjunct_url"), row.get("adjunct_type"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("GB200 候选 PDF 抽取失败: %s", exc)
        row["text"] = body
        if body:
            row["score"] = _score_announcement(str(row.get("title") or ""), body)
            if _body_has_gb200_signal(body):
                row["score"] = max(int(row["score"]), 28)
        out.append(row)
    # 保留未拉 PDF 的其余候选（低优先级）
    seen = {c.get("adjunct_url") or c.get("title") for c in out}
    for cand in ranked[limit:]:
        key = cand.get("adjunct_url") or cand.get("title")
        if key not in seen:
            out.append(cand)
    return out


def _normalize_pdf_text(text: str) -> str:
    """PDF 抽取常含换行断句 · 归一化后再做里程碑摘录。"""
    return re.sub(r"\s+", " ", (text or "").strip())


def _extract_milestone_excerpt(text: str, *, max_len: int = 2400) -> str:
    norm = _normalize_pdf_text(text)
    if not norm:
        return ""

    gb200 = re.search(r"GB200.{0,420}", norm, re.I)
    if gb200:
        start = max(0, gb200.start() - 160)
        return norm[start : start + max_len].strip()

    for pat in (
        r"(?:NVL72|NVL36|智算机柜|Blackwell).{0,320}",
        r"规模交付.{0,240}",
        r"量产爬坡.{0,240}",
        r"批量交付.{0,240}",
    ):
        m = re.search(pat, norm, re.I)
        if m:
            start = max(0, m.start() - 120)
            return norm[start : start + max_len].strip()

    return norm[:max_len]


def _event_text_for_mapping(title: str, body: str) -> str:
    """PDF 失败/超大年报时 · 标题 + 已抽取片段仍可用于状态机映射。"""
    title = title.strip()
    body = body.strip()
    if len(body) >= 120:
        excerpt = _extract_milestone_excerpt(body)
        if len(excerpt) >= 40:
            return f"{title}\n{excerpt}" if title else excerpt
    blob = _normalize_pdf_text(f"{title}\n{body}")
    excerpt = _extract_milestone_excerpt(blob)
    if len(excerpt) >= 40:
        return f"{title}\n{excerpt}" if title and title not in excerpt else excerpt
    if len(title) >= 20:
        return title
    return blob[:1200]


def _is_generic_periodic(title: str) -> bool:
    if _MEETING_NOTICE_TITLE.search(title) and not re.search(
        r"GB200|NVL|智算|机柜|Blackwell|规模交付|量产", title, re.I
    ):
        return True
    if not _PERIODIC_REPORT_TITLE.search(title):
        return False
    return not re.search(r"GB200|NVL|智算|机柜|Blackwell|规模交付", title, re.I)


def fetch_gb200_official_event(symbol: str) -> dict[str, Any]:
    """近 12 个月巨潮公告 · 标题+PDF 正文联合评分 · GB200/智算机柜里程碑。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text, iter_cninfo_announcements

    sym = symbol.zfill(6)[-6:]
    end = datetime.now(_CST)
    start = event_window_start(ref=end)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for kw in (
        "GB200",
        "智算",
        "机柜",
        "NVL",
        "Blackwell",
        "AI服务器",
        "半年度报告",
        "年度报告",
        "",
    ):
        for item in iter_cninfo_announcements(
            sym,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            category="",
            keyword=kw,
            max_pages=5 if kw else 10,
            throttle_sec=0.2,
        ):
            title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or "")).strip()
            if not title or _SKIP_TITLE.search(title):
                continue
            url = str(item.get("adjunctUrl") or "")
            dedupe = url or title
            if dedupe in seen:
                continue
            seen.add(dedupe)

            score = _score_announcement(title, "")
            if score < 8 and kw == "":
                continue
            candidates.append(
                {
                    "title": title,
                    "text": "",
                    "score": score,
                    "published_date": _parse_pub_date(item),
                    "adjunct_url": url,
                    "adjunct_type": item.get("adjunctType"),
                    "source_kw": kw,
                }
            )

    if not candidates:
        return {"ok": False, "blocker": "[B] 近12个月巨潮无 GB200/智算机柜相关公告"}

    candidates = [
        c for c in candidates if is_within_event_window(c.get("published_date"), ref=end)
    ]
    if not candidates:
        return {
            "ok": False,
            "blocker": "[B] 近12个月巨潮无 GB200/智算机柜相关公告（命中条目均超出分析窗口）",
        }

    candidates = _rescore_candidates_with_pdf(candidates, limit=14)
    milestone_candidates = [
        c
        for c in candidates
        if not _is_generic_periodic(c["title"]) or _body_has_gb200_signal(str(c.get("text") or ""))
    ]
    pool = milestone_candidates if milestone_candidates else candidates

    best = max(pool, key=_candidate_rank_key)
    if int(best["score"]) < 12 and not _body_has_gb200_signal(str(best.get("text") or "")):
        return {
            "ok": False,
            "blocker": "[D] 已扫巨潮公告·无 GB200/量产节点关键词命中（非准出）",
            "titles_scanned": len(candidates),
        }

    body = str(best.get("text") or "")
    url = str(best.get("adjunct_url") or "")
    if not body and url:
        try:
            body = fetch_cninfo_adjunct_pdf_text(best.get("adjunct_url"), best.get("adjunct_type"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("GB200 最佳公告 PDF 抽取失败: %s", exc)

    excerpt = _event_text_for_mapping(best["title"], body)
    if len(excerpt) < 20:
        return {
            "ok": False,
            "blocker": "[B] 命中公告但正文过短·无法做生命周期映射",
            "announcement_title": best["title"],
        }

    return {
        "ok": True,
        "source": f"cninfo:{best.get('source_kw') or 'scan'}",
        "announcement_title": best["title"],
        "official_announcement_text": excerpt,
        "published_date": best.get("published_date"),
        "adjunct_url": best.get("adjunct_url"),
        "match_score": best["score"],
        "pdf_chars": len(body),
        "analysis_window": event_window_meta(ref=end),
    }


def fetch_investor_relations_qa(symbol: str) -> dict[str, Any]:
    """近 6 个月 IR 实录 · GB200 进度问答补充。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text, iter_cninfo_announcements
    from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t0_cninfo import (
        _PREFER_QA_TITLE,
        _QA_CONTENT_MARKERS,
        _SKIP_QA_TITLE,
        _qa_candidate_score,
    )

    sym = symbol.zfill(6)[-6:]
    end = datetime.now(_CST)
    start = event_window_start(ref=end)
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for kw in ("投资者关系活动", "活动记录表", "投资者关系", "业绩说明会", "调研", ""):
        for item in iter_cninfo_announcements(
            sym,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            category="",
            keyword=kw,
            max_pages=4 if kw else 6,
            throttle_sec=0.2,
        ):
            title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or ""))
            if _SKIP_QA_TITLE.search(title):
                continue
            if kw == "" and not _PREFER_QA_TITLE.search(title):
                continue
            pub = _parse_pub_date(item)
            if pub and not is_within_event_window(pub, ref=end):
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
                    "published_date": pub,
                }
            )

    if not candidates:
        return {"ok": False, "blocker": "近6个月无 IR 活动记录表 / QA 实录"}

    best = max(candidates, key=lambda c: (int(c["score"]), str(c.get("published_date") or "")))
    if int(best["score"]) < 0:
        return {"ok": False, "blocker": "近6个月仅命中召开预告，无 IR 活动记录表"}

    text = str(best.get("text") or "")
    gb200_chunk = ""
    for pat in (r"GB200.{0,400}", r"NVL.{0,400}", r"智算机柜.{0,300}", r"Blackwell.{0,300}"):
        m = re.search(pat, text, re.I | re.S)
        if m:
            gb200_chunk = re.sub(r"\s+", " ", m.group(0))[:1500]
            break
    return {
        "ok": True,
        "source": best.get("source"),
        "report_title": best.get("title"),
        "published_date": best.get("published_date"),
        "investor_relations_qa": gb200_chunk or text[:2000],
        "qa_full_chars": len(text),
        "analysis_window": event_window_meta(ref=end),
    }
