"""巨潮资讯网公告全文（可 mock / 重试）。"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def fetch_full_announcement_text(
    announcement_id: str,
    base_url: str = "https://www.cninfo.com.cn",
    adjunct_path: str | None = None,
    adjunct_type: str | None = None,
) -> str:
    """拉取公告正文：若提供 ``adjunctUrl`` 则优先解析巨潮 PDF 文本。"""
    if adjunct_path:
        try:
            from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text  # noqa: PLC0415

            body = fetch_cninfo_adjunct_pdf_text(adjunct_path, adjunct_type)
            if body:
                return body[:65536]
        except Exception as exc:
            logger.warning("cninfo pdf text fail %s: %s", adjunct_path, exc)
    url = f"{base_url}/new/disclosure/detail?announcementId={announcement_id}"
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(url, headers={"User-Agent": "diting-data/1.0"})
            r.raise_for_status()
            return r.text[:65536]
    except Exception as exc:
        logger.warning("cninfo fetch fail %s: %s", announcement_id, exc)
        return ""
