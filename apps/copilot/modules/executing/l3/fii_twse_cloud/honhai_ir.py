"""鸿海 IR 月营收简报 · Playwright 主路径 + httpx/OCR 兜底。

[Ref: 28_ §2.2 fii_twse_cloud · pr_raw_text]
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from apps.copilot.modules.executing.l3.fii_twse_cloud.constants import HONHAI_MONTHLY_CATEGORY_PATH

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Diting-Copilot/1.0)"}
_TIMEOUT = 45.0
_BASE = "https://www.honhai.com"
_MIN_PR_LEN = int(os.environ.get("FII_TWSE_PR_MIN_LEN", "40"))
_NARRATIVE = re.compile(r"(云端|雲端|消费|消費|电脑|電腦|元件).{0,20}(方面|产品|產品|類別|类别)")
_TABLE = re.compile(r"營業收入|营业输入|月增\(減\)|Monthly_Revenue")


def _pr_text_usable(text: str) -> bool:
    t = (text or "").strip()
    return len(t) >= _MIN_PR_LEN and bool(_NARRATIVE.search(t) or _TABLE.search(t))


def _parse_nuxt_data(html: str) -> list[Any]:
    import json

    m = re.search(r'id="__NUXT_DATA__"[^>]*>(\[.*\])</script>', html, re.S)
    if not m:
        return []
    return json.loads(m.group(1))


def _month_en(month: int) -> str:
    names = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    return names[month - 1] if 1 <= month <= 12 else ""


def _find_monthly_article_id(arr: list[Any], year: int, month: int) -> int | None:
    title_pat = re.compile(rf"公告{year}年{month:02d}月自結合併營收")
    raw = str(arr)
    for m in re.finditer(r",(\d{3,5}),\"([^\"]*自結合併營收[^\"]*)\"", raw):
        art_id, title = int(m.group(1)), m.group(2)
        if title_pat.search(title):
            return art_id
    return None


def _extract_image_urls(html: str) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(
                r"https://image\.honhai\.com/upload/[^\"'\s]+Monthly_Revenue[^\"'\s]+\.(?:jpg|jpeg|png)",
                html,
                re.I,
            )
        )
    )


def _ocr_single(url: str) -> str:
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return ""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        return pytesseract.image_to_string(img, lang="chi_tra+eng").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR 失败 %s: %s", url, exc)
        return ""


def _ocr_images(urls: list[str]) -> tuple[str, list[dict[str, str]]]:
    """逐页 OCR · 返回合并正文 + 分页明细（供溯源）。"""
    pages: list[dict[str, str]] = []
    parts: list[str] = []
    for idx, url in enumerate(urls, start=1):
        text = _ocr_single(url)
        pages.append({"page": str(idx), "url": url, "text": text})
        if text:
            parts.append(text)
    return "\n\n".join(parts), pages


def _fetch_http_fallback(*, year: int, month: int) -> dict[str, Any]:
    """httpx 探测文章 + OCR 图片（Playwright 不可用时的兜底）。"""
    month_en = _month_en(month)
    pat = re.compile(rf"Monthly_Revenue_Report_{month_en}_{year}", re.I)
    for aid in range(2035, 1985, -1):
        art_url = f"{_BASE}/zh-tw/press-center/press-releases/latest-news/{aid}"
        try:
            art_html = requests.get(art_url, headers=_HEADERS, timeout=20).text
        except Exception:  # noqa: BLE001
            continue
        if pat.search(art_html):
            img_urls = _extract_image_urls(art_html)
            ocr_text, ocr_pages = _ocr_images(img_urls)
            return {
                "pr_raw_text": ocr_text.strip(),
                "pr_image_urls": img_urls,
                "pr_ocr_pages": ocr_pages,
                "article_id": aid,
                "article_url": art_url,
                "source": "Hon Hai IR · httpx + OCR fallback",
                "ocr_applied": bool(ocr_text),
                "playwright": False,
            }
    return {
        "pr_raw_text": "",
        "pr_image_urls": [],
        "pr_ocr_pages": [],
        "article_id": None,
        "article_url": None,
        "source": "Hon Hai IR · httpx fallback miss",
        "playwright": False,
    }


def _apply_ocr(result: dict[str, Any]) -> dict[str, Any] | None:
    imgs = result.get("pr_image_urls") or []
    if not imgs:
        return None
    ocr, pages = _ocr_images(imgs)
    if not _pr_text_usable(ocr):
        return None
    result = dict(result)
    result["pr_raw_text"] = ocr.strip()
    result["pr_ocr_pages"] = pages
    result["source"] = result.get("source", "Hon Hai IR") + " + OCR(images)"
    result["ocr_applied"] = True
    return result


def _run_playwright_fetch(*, year: int, month: int) -> dict[str, Any]:
    from apps.copilot.modules.executing.l3.fii_twse_cloud.honhai_playwright import (
        fetch_monthly_pr_text_playwright,
    )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fetch_monthly_pr_text_playwright(year=year, month=month)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fetch_monthly_pr_text_playwright, year=year, month=month)
        return future.result(timeout=120)


def fetch_monthly_pr_text(*, year: int, month: int) -> dict[str, Any]:
    """抓取当月营收简报 pr_raw_text · Playwright 优先，全页 OCR 合并。"""
    use_pw = os.environ.get("FII_TWSE_USE_PLAYWRIGHT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    if use_pw:
        try:
            result = _run_playwright_fetch(year=year, month=month)
            text = (result.get("pr_raw_text") or "").strip()
            if _pr_text_usable(text) and _NARRATIVE.search(text):
                return result
            logger.warning(
                "Playwright 正文需 OCR 补强(len=%d, narrative=%s)",
                len(text),
                bool(_NARRATIVE.search(text)),
            )
            ocr_result = _apply_ocr(result)
            if ocr_result:
                return ocr_result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playwright 抓取失败 · 回退 httpx: %s", exc)

    cat_url = f"{_BASE}{HONHAI_MONTHLY_CATEGORY_PATH}"
    try:
        cat_html = requests.get(cat_url, headers=_HEADERS, timeout=_TIMEOUT).text
        arr = _parse_nuxt_data(cat_html)
        article_id = _find_monthly_article_id(arr, year, month) if arr else None
        if article_id:
            art_url = f"{_BASE}/zh-tw/press-center/press-releases/latest-news/{article_id}"
            art_html = requests.get(art_url, headers=_HEADERS, timeout=_TIMEOUT).text
            img_urls = _extract_image_urls(art_html)
            ocr_text, ocr_pages = _ocr_images(img_urls)
            if _pr_text_usable(ocr_text):
                return {
                    "pr_raw_text": ocr_text.strip(),
                    "pr_image_urls": img_urls,
                    "pr_ocr_pages": ocr_pages,
                    "article_id": article_id,
                    "article_url": art_url,
                    "source": "Hon Hai IR · NUXT + OCR fallback",
                    "ocr_applied": True,
                    "playwright": False,
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("httpx 分类页失败: %s", exc)

    return _fetch_http_fallback(year=year, month=month)
