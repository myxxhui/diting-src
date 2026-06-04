"""巨潮年报附注解析 · 前五客户 / 分部（完善期 · 无 mock）。

[Ref: 28_ §9 · 27_ T0-5/T0-6]
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CUSTOMER_SECTION = re.compile(
    r"前五名客户(?:的)?(?:销售|客户).*?(?=前五名供应商|主要供应商|分(?:部|行业|地区)|$)",
    re.S,
)
_AGGREGATE_CUSTOMER = re.compile(
    r"前五名客户销售额\s*(?P<amount>[\d,，.]+)\s*万元"
    r".*?占年度销售总额\s*(?P<pct>[\d.]+)\s*%",
    re.S,
)
_EXEMPT_DISCLOSURE = re.compile(r"豁免披露|商业秘密|未披露.*?客户名称")


def _latest_annual_report_item(symbol: str) -> dict[str, Any] | None:
    from apps.cryo_guard.cninfo_client import iter_cninfo_announcements

    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=400)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    best: dict[str, Any] | None = None
    for item in iter_cninfo_announcements(
        symbol,
        start_s,
        end_s,
        category="年报",
        max_pages=3,
        throttle_sec=0.25,
    ):
        title = str(item.get("announcementTitle") or "")
        if "摘要" in title:
            continue
        if "年度报告" in title or title.endswith("年报"):
            best = item
            break
    return best


_HEADER_WORDS = frozenset(
    {"前五", "售额", "客户", "名称", "序号", "合计", "总计", "销售", "金额", "比例", "占", "年度"}
)


def fetch_top5_customers_from_annual(symbol: str) -> dict[str, Any]:
    """T0-6 · 年报 PDF 前五名客户表（巨潮 · 无披露即 error）。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text

    item = _latest_annual_report_item(symbol)
    if not item:
        return {
            "status": "error",
            "detail": "T0-6 未找到近一年巨潮年报公告",
        }

    text = fetch_cninfo_adjunct_pdf_text(
        item.get("adjunctUrl"),
        item.get("adjunctType"),
    )
    if not text or len(text) < 500:
        return {
            "status": "error",
            "detail": "T0-6 年报 PDF 正文抽取失败或过短",
        }

    exempt = bool(_EXEMPT_DISCLOSURE.search(text))
    agg = _AGGREGATE_CUSTOMER.search(text)
    if agg:
        try:
            amount_wan = float(str(agg.group("amount")).replace(",", "").replace("，", ""))
        except ValueError:
            amount_wan = None
        try:
            top5_pct = float(str(agg.group("pct")).replace("%", ""))
        except ValueError:
            top5_pct = None
        if top5_pct is not None:
            out: dict[str, Any] = {
                "status": "ok",
                "source": "cninfo:annual_report_pdf",
                "report_title": item.get("announcementTitle"),
                "customers": [],
                "top5_customer_pct": round(top5_pct, 4),
                "top5_sales_amount_wan": amount_wan,
            }
            if exempt:
                out["disclosure"] = "aggregate_only"
                out["detail"] = "前五名客户名称豁免披露（商业秘密），仅汇总占比可用"
            return out

    section = _CUSTOMER_SECTION.search(text)
    chunk = section.group(0) if section else ""
    if not chunk:
        idx = text.find("前五名客户")
        if idx < 0:
            return {"status": "error", "detail": "T0-6 年报无前五名客户披露段落"}
        chunk = text[idx : idx + 2500]

    customers: list[dict[str, Any]] = []
    top5_pct = 0.0
    for line in chunk.splitlines():
        line = line.strip()
        if len(line) < 4:
            continue
        if any(w == line for w in _HEADER_WORDS):
            continue
        m = re.search(
            r"^(?:[一二三四五1-5][、.)]?\s*)?(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()·\-\s]{2,40}?)"
            r"(?:\s+(?P<amount>[\d,，.]+))?"
            r"(?:\s+(?P<pct>[\d.]+%))?$",
            line,
        )
        if not m:
            continue
        name = (m.group("name") or "").strip()
        if len(name) < 3 or name in _HEADER_WORDS or any(w in name for w in ("客户名称", "销售金额")):
            continue
        pct_s = m.group("pct")
        pct = None
        if pct_s:
            try:
                pct = float(str(pct_s).replace("%", ""))
                top5_pct += pct
            except ValueError:
                pct = None
        customers.append({"name": name, "sales_pct": pct})
        if len(customers) >= 5:
            break

    if not customers or all(c["name"] in _HEADER_WORDS for c in customers):
        return {"status": "error", "detail": "T0-6 前五名客户表解析为空"}

    return {
        "status": "ok",
        "source": "cninfo:annual_report_pdf",
        "report_title": item.get("announcementTitle"),
        "customers": customers,
        "top5_customer_pct": round(top5_pct, 4) if top5_pct else None,
    }
