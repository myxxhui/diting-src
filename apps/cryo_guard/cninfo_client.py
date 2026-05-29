"""巨潮资讯网（cninfo）公开数据客户端：公告检索、PDF 地址与正文抽取。

信息披露为免费公开访问；调用时仍须遵守站点条款、控制频率与并发。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import io
import logging
import math
import os
import time
from functools import lru_cache
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)

CNINFO_STOCK_JSON = "http://www.cninfo.com.cn/new/data/szse_stock.json"
STATIC_BASE = "http://static.cninfo.com.cn"


@lru_cache(maxsize=1)
def _stock_org_map() -> dict[str, str]:
    r = requests.get(CNINFO_STOCK_JSON, timeout=60)
    r.raise_for_status()
    data = r.json()
    out: dict[str, str] = {}
    for item in data.get("stockList") or []:
        code = str(item.get("code") or "").strip()
        oid = str(item.get("orgId") or "").strip()
        if code and oid:
            out[code] = oid
    return out


def cninfo_stock_token(symbol: str) -> str:
    """``secCode,orgId`` 供巨潮 query 使用。"""
    s = symbol.strip().zfill(6)[-6:]
    omap = _stock_org_map()
    if s not in omap:
        raise KeyError(f"巨潮股票表无代码 {s!r}，请检查是否沪深京 A 股")
    return f"{s},{omap[s]}"


def _post_query(payload: dict[str, str]) -> dict[str, Any]:
    """巨潮接口对 form 与 query 均接受，统一用 data。"""
    r = requests.post(
        "http://www.cninfo.com.cn/new/hisAnnouncement/query",
        data=payload,
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 (compatible; diting-cryo-guard/1.0)"},
    )
    r.raise_for_status()
    return r.json()


def iter_cninfo_announcements(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    category: str = "",
    keyword: str = "",
    page_size: int = 30,
    max_pages: int | None = None,
    throttle_sec: float = 0.0,
) -> Iterator[dict[str, Any]]:
    """分页迭代单只股票的公告元数据（原始 JSON 对象列表项）。

    :param start_date/end_date: ``YYYYMMDD``
    :param category: 巨潮类别中文名，如 ``年报``；空表示不限类别
    """
    from akshare.stock_feature.stock_disclosure_cninfo import (  # noqa: PLC0415
        __get_category_dict,
    )

    cat_dict = __get_category_dict()
    if category and category not in cat_dict:
        raise ValueError(f"未知巨潮公告类别 {category!r}（参见 akshare stock_zh_a_disclosure_report_cninfo 文档）")
    category_item = "" if not category else cat_dict[category]
    stock_item = cninfo_stock_token(symbol)
    se_d = (
        f'{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}~'
        f'{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}'
    )
    payload: dict[str, str] = {
        "pageNum": "1",
        "pageSize": str(page_size),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_item,
        "searchkey": keyword,
        "secid": "",
        "category": category_item,
        "trade": "",
        "seDate": se_d,
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    first = _post_query(payload)
    total = int(first.get("totalAnnouncement") or 0)
    if total == 0:
        return
    n_pages = max(1, math.ceil(total / page_size))
    if max_pages is not None:
        n_pages = min(n_pages, max_pages)

    def _page(p: int) -> list[dict[str, Any]]:
        pld = dict(payload)
        pld["pageNum"] = str(p)
        return (_post_query(pld).get("announcements") or [])

    for item in first.get("announcements") or []:
        yield item

    for p in range(2, n_pages + 1):
        if throttle_sec > 0:
            time.sleep(throttle_sec)
        for item in _page(p):
            yield item


def static_file_url(adjunct_path: str | None) -> str | None:
    if not adjunct_path or not str(adjunct_path).strip():
        return None
    path = str(adjunct_path).strip().lstrip("/")
    return f"{STATIC_BASE}/{path}"


def download_pdf_bytes(url: str, max_bytes: int) -> bytes:
    r = requests.get(
        url,
        timeout=120,
        headers={"User-Agent": "Mozilla/5.0 (compatible; diting-cryo-guard/1.0)"},
        stream=True,
    )
    r.raise_for_status()
    chunks: list[bytes] = []
    n = 0
    for chunk in r.iter_content(chunk_size=65536):
        if not chunk:
            continue
        chunks.append(chunk)
        n += len(chunk)
        if n > max_bytes:
            raise ValueError(f"PDF 超过 CRYO_ANN_PDF_MAX_BYTES 限制 ({max_bytes})")
    return b"".join(chunks)


def extract_pdf_text(
    pdf_bytes: bytes,
    *,
    max_pages: int,
    max_chars: int,
) -> str:
    import pdfplumber  # noqa: PLC0415

    parts: list[str] = []
    total = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            txt = page.extract_text() or ""
            if not txt.strip():
                continue
            if total + len(txt) > max_chars:
                take = max_chars - total
                if take > 0:
                    parts.append(txt[:take])
                break
            parts.append(txt)
            total += len(txt)
    return "\n".join(parts).strip()


def fetch_cninfo_adjunct_pdf_text(
    adjunct_path: str | None,
    adjunct_type: str | None = None,
) -> str:
    """从 ``adjunctUrl`` 拉取 PDF 并抽取文本；非 PDF 或失败返回空串。"""
    if not adjunct_path:
        return ""
    t = (adjunct_type or "").upper()
    if t and "PDF" not in t:
        return ""
    url = static_file_url(adjunct_path)
    if not url:
        return ""
    max_bytes = int(os.environ.get("CRYO_ANN_PDF_MAX_BYTES", str(30 * 1024 * 1024)))
    max_pages = int(os.environ.get("CRYO_ANN_PDF_MAX_PAGES", "80"))
    max_chars = int(os.environ.get("CRYO_ANN_PDF_MAX_CHARS", "500000"))
    try:
        data = download_pdf_bytes(url, max_bytes=max_bytes)
        return extract_pdf_text(data, max_pages=max_pages, max_chars=max_chars)
    except Exception as exc:
        logger.warning("巨潮 PDF 正文抽取失败 %s: %s", url, exc)
        return ""
