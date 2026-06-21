"""Z0 政策 T0 ingest · HTML 列表 → deepsea_doc_registry（全文 · no-mock · 去重）。

[Ref: 29_ §5.1 · 34_ §3.2 M.policy.sector_direction · z0_history_contract.yaml]
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import yaml
from sqlalchemy import create_engine, text

from apps.copilot.services.deepsea.policy_reader import load_policy_keywords

logger = logging.getLogger(__name__)

POLICY_DOC_TYPE = "policy"
_FEEDS_CFG = (
    Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_feeds.yaml"
)
_HISTORY_CFG = (
    Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_history_contract.yaml"
)
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text_parts: list[str] = []
        self._in_a = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._in_a = True
        self._href = dict(attrs).get("href") or ""
        self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._in_a:
            return
        text = "".join(self._text_parts).strip()
        if self._href and text:
            self.links.append((self._href, text))
        self._in_a = False

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._text_parts.append(data)


def _sync_db_url() -> str:
    import os

    raw = (os.environ.get("COPILOT_DB_URL") or "sqlite+aiosqlite:///./data/copilot.db").strip()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return raw


def _load_feeds_cfg() -> dict[str, Any]:
    if not _FEEDS_CFG.is_file():
        return {"feeds": [], "max_items_per_feed": 20, "lookback_days": 730}
    with _FEEDS_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_policy_t0_cfg() -> dict[str, Any]:
    if not _HISTORY_CFG.is_file():
        return {}
    with _HISTORY_CFG.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("policy_t0") or {}


def _doc_id_from_url(url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip()))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        tp = entry.get(key)
        if tp:
            try:
                return datetime(*tp[:6], tzinfo=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                pass
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            dt = parsedate_to_datetime(str(raw))
            return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except (TypeError, ValueError):
            pass
    return None


def _parse_date_from_url(url: str) -> datetime | None:
    for pat in (
        r"/(\d{4}-\d{2})/(\d{2})/",  # /2014-02/17/  (NEA)
        r"/(\d{4}-\d{2})/",          # /2014-02/     (NEA fallback)
        r"/(\d{6})/",                # /202604/      (MOST/MOT/MOF)
        r"/(\d{4})/",                # /2026/        (year only)
    ):
        match = re.search(pat, url)
        if match:
            if pat.startswith(r"/(\d{4}-\d{2})/(\d{2})"):
                try:
                    return datetime.strptime(match.group(1) + "-" + match.group(2), "%Y-%m-%d")
                except ValueError:
                    continue
            elif pat.startswith(r"/(\d{4}-\d{2})"):
                try:
                    return datetime.strptime(match.group(1), "%Y-%m")
                except ValueError:
                    continue
            else:
                token = match.group(1)
                fmt = "%Y%m" if len(token) == 6 else "%Y"
                try:
                    return datetime.strptime(token, fmt)
                except ValueError:
                    continue
    return None


def _match_themes(text: str) -> list[str]:
    aliases = load_policy_keywords().get("sector_aliases") or {}
    themes: list[str] = []
    for sector, kws in aliases.items():
        if any(kw in text for kw in kws):
            themes.append(sector)
    return themes


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    html = re.sub(r"(?is)<(br|p|div|tr|li|h\d)[^>]*>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&gt;", ">").replace("&lt;", "<")
    lines = [ln.strip() for ln in html.splitlines() if ln.strip()]
    return "\n".join(lines)


def fetch_policy_full_text(url: str, *, timeout_sec: float = 20.0) -> tuple[str, str | None]:
    """抓取政策正文 · 返回 (text, error)。"""
    try:
        response = httpx.get(
            url,
            headers=_HTTP_HEADERS,
            timeout=timeout_sec,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)[:120]

    html = response.text
    # gov.cn 常见正文容器
    for pat in (
        r'(?is)<div[^>]*class="[^"]*pages_content[^"]*"[^>]*>(.*?)</div>',
        r'(?is)<div[^>]*class="[^"]*TRS_Editor[^"]*"[^>]*>(.*?)</div>',
        r'(?is)<div[^>]*id="UCAP-CONTENT"[^>]*>(.*?)</div>',
        r'(?is)<article[^>]*>(.*?)</article>',
    ):
        m = re.search(pat, html)
        if m and len(m.group(1)) > 200:
            return _strip_html(m.group(1)), None
    return _strip_html(html), None


def register_policy_doc(
    *,
    url: str,
    title: str,
    summary: str,
    source: str,
    feed_id: str,
    published_at: datetime | None,
    full_text: str | None = None,
    feed_tier: str | None = None,
) -> str | None:
    """写入 deepsea_doc_registry · 按 doc_id/content_sha256 幂等。"""
    if not url.strip() or not title.strip():
        return None
    doc_id = _doc_id_from_url(url)
    body_parts = [title, summary or ""]
    if full_text:
        body_parts.append(full_text)
    body = "\n".join(body_parts)
    content_hash = _sha256(body)
    themes = _match_themes(body)
    lineage: dict[str, Any] = {
        "title": title[:500],
        "summary": (summary or title)[:2000],
        "link": url,
        "source": source,
        "feed_id": feed_id,
        "themes": themes,
    }
    if feed_tier:
        lineage["tier"] = feed_tier
    if full_text:
        lineage["full_text"] = full_text[:48000]
        lineage["full_text_len"] = len(full_text)
        lineage["full_text_truncated"] = len(full_text) > 48000
    parsed_uri = f"inline:text/plain;chars={len(full_text or summary or title)}"

    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT doc_id FROM deepsea_doc_registry "
                    "WHERE doc_id = :doc_id OR content_sha256 = :sha"
                ),
                {"doc_id": doc_id, "sha": content_hash},
            ).first()
            if existing:
                return None
            conn.execute(
                text(
                    """
                    INSERT INTO deepsea_doc_registry (
                        doc_id, symbol, doc_type, object_uri, parsed_uri,
                        published_at, lineage_tags, content_sha256
                    ) VALUES (
                        :doc_id, NULL, :doc_type, :object_uri, :parsed_uri,
                        :published_at, :lineage_tags, :content_sha256
                    )
                    """
                ),
                {
                    "doc_id": doc_id,
                    "doc_type": POLICY_DOC_TYPE,
                    "object_uri": url,
                    "parsed_uri": parsed_uri,
                    "published_at": published_at,
                    "lineage_tags": json.dumps(lineage, ensure_ascii=False),
                    "content_sha256": content_hash,
                },
            )
        return doc_id
    finally:
        engine.dispose()


def _register_item(
    *,
    link: str,
    title: str,
    summary: str,
    source: str,
    feed_id: str,
    published: datetime | None,
    cutoff: datetime,
    fetch_full_text: bool,
    full_text_max: int,
    min_full_text: int,
    feed_tier: str | None,
    timeout_sec: float,
) -> tuple[str | None, bool, bool]:
    if published and published < cutoff:
        return None, True, False
    full_text = ""
    if fetch_full_text and link.startswith("http"):
        full_text, _err = fetch_policy_full_text(link, timeout_sec=timeout_sec)
        if full_text and len(full_text) < min_full_text:
            full_text = ""
        if full_text and len(full_text) > full_text_max:
            full_text = full_text[:full_text_max]
        time.sleep(0.35)  # 礼貌限速
    doc_id = register_policy_doc(
        url=link or title,
        title=title,
        summary=summary[:2000] if summary else title,
        source=source,
        feed_id=feed_id,
        published_at=published,
        full_text=full_text or None,
        feed_tier=feed_tier,
    )
    if doc_id:
        return doc_id, False, bool(full_text)
    return None, True, False


def _ingest_html_list_feed(
    feed: dict[str, Any],
    *,
    max_items: int,
    cutoff: datetime,
    timeout_sec: float,
    fetch_full_text: bool,
    full_text_max: int,
    min_full_text: int,
) -> tuple[int, int, int, str | None]:
    feed_id = str(feed.get("id") or "unknown")
    url = str(feed.get("url") or "").strip()
    source = str(feed.get("source") or feed_id)
    href_contains = str(feed.get("href_contains") or "").strip()
    min_title_len = int(feed.get("min_title_len") or 10)
    feed_tier = feed.get("tier")

    response = httpx.get(
        url,
        headers=_HTTP_HEADERS,
        timeout=timeout_sec,
        follow_redirects=True,
    )
    response.raise_for_status()

    parser = _LinkParser()
    parser.feed(response.text)

    seen: set[str] = set()
    new_count = 0
    skipped = 0
    fulltext_count = 0

    for href, title in parser.links:
        link = urljoin(url, href)
        if href_contains and href_contains not in link:
            continue
        if len(title) < min_title_len:
            continue
        if link in seen:
            continue
        seen.add(link)

        published = _parse_date_from_url(link)
        doc_id, was_skipped, got_full = _register_item(
            link=link,
            title=title,
            summary=title,
            source=source,
            feed_id=feed_id,
            published=published,
            cutoff=cutoff,
            fetch_full_text=fetch_full_text,
            full_text_max=full_text_max,
            min_full_text=min_full_text,
            feed_tier=str(feed_tier) if feed_tier else None,
            timeout_sec=timeout_sec,
        )
        if doc_id:
            new_count += 1
            if got_full:
                fulltext_count += 1
        elif was_skipped:
            skipped += 1
        if new_count + skipped >= max_items:
            break

    if not seen:
        return new_count, skipped, fulltext_count, "empty_list"
    return new_count, skipped, fulltext_count, None


def _ingest_rss_feed(
    feed: dict[str, Any],
    *,
    max_items: int,
    cutoff: datetime,
    timeout_sec: float,
    fetch_full_text: bool,
    full_text_max: int,
    min_full_text: int,
) -> tuple[int, int, int, str | None]:
    import feedparser

    feed_id = str(feed.get("id") or "unknown")
    url = str(feed.get("url") or "").strip()
    source = str(feed.get("source") or feed_id)
    feed_tier = feed.get("tier")

    response = httpx.get(
        url,
        headers=_HTTP_HEADERS,
        timeout=timeout_sec,
        follow_redirects=True,
    )
    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        return 0, 0, 0, "parse_failed"

    new_count = 0
    skipped = 0
    fulltext_count = 0
    for entry in (parsed.entries or [])[:max_items]:
        link = str(getattr(entry, "link", "") or "").strip()
        title = str(getattr(entry, "title", "") or "").strip()
        summary = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
        published = _parse_published(entry.__dict__ if hasattr(entry, "__dict__") else {})
        doc_id, was_skipped, got_full = _register_item(
            link=link or title,
            title=title,
            summary=summary,
            source=source,
            feed_id=feed_id,
            published=published,
            cutoff=cutoff,
            fetch_full_text=fetch_full_text,
            full_text_max=full_text_max,
            min_full_text=min_full_text,
            feed_tier=str(feed_tier) if feed_tier else None,
            timeout_sec=timeout_sec,
        )
        if doc_id:
            new_count += 1
            if got_full:
                fulltext_count += 1
        elif was_skipped:
            skipped += 1
    if not parsed.entries:
        return new_count, skipped, fulltext_count, "empty_list"
    return new_count, skipped, fulltext_count, None


def _ingest_api_paginated_feed(
    feed: dict[str, Any],
    *,
    max_items: int,
    cutoff: datetime,
    timeout_sec: float,
    fetch_full_text: bool,
    full_text_max: int,
    min_full_text: int,
) -> tuple[int, int, int, str | None]:
    """API 分页列表采集（商务部等 JS 渲染页面用后端分页 API 替代）。"""
    import json as _json
    from urllib.parse import urlencode

    feed_id = str(feed.get("id") or "unknown")
    source = str(feed.get("source") or feed_id)
    href_contains = str(feed.get("href_contains") or "").strip()
    min_title_len = int(feed.get("min_title_len") or 10)
    feed_tier = feed.get("tier")
    page_size = int(feed.get("page_size") or 15)
    max_pages = int(feed.get("max_pages") or 154)
    # API 专有参数
    api_params = feed.get("api_params") or {}

    new_count = 0
    skipped = 0
    fulltext_count = 0
    seen: set[str] = set()

    for page_no in range(1, max_pages + 1):
        param_json = _json.dumps({"pageNo": page_no, "pageSize": str(page_size)}, separators=(",", ":"))
        query = {
            "parseType": str(api_params.get("parseType", "bulidstatic")),
            "webId": str(api_params.get("webId", "")),
            "tplSetId": str(api_params.get("tplSetId", "")),
            "pageType": str(api_params.get("pageType", "column")),
            "tagId": str(api_params.get("tagId", "列表")),
            "editType": str(api_params.get("editType", "null")),
            "pageId": str(api_params.get("pageId", "")),
            "paramJson": param_json,
        }
        api_url = str(feed.get("url") or "").strip()
        if page_no == 1 and not api_url:
            return 0, 0, 0, "empty_api_url"

        try:
            response = httpx.get(
                api_url,
                params=query,
                headers=_HTTP_HEADERS,
                timeout=timeout_sec,
                follow_redirects=True,
            )
            response.raise_for_status()
        except Exception as exc:
            if page_no == 1:
                return 0, 0, 0, str(exc)
            break

        parser = _LinkParser()
        parser.feed(response.text)

        page_has_articles = False
        for href, title in parser.links:
            link = urljoin("https://www.mofcom.gov.cn", href)
            if href_contains and href_contains not in link:
                continue
            if len(title) < min_title_len:
                continue
            if link in seen:
                continue
            seen.add(link)
            page_has_articles = True

            published = _parse_date_from_url(link)
            doc_id, was_skipped, got_full = _register_item(
                link=link,
                title=title,
                summary=title,
                source=source,
                feed_id=feed_id,
                published=published,
                cutoff=cutoff,
                fetch_full_text=fetch_full_text,
                full_text_max=full_text_max,
                min_full_text=min_full_text,
                feed_tier=str(feed_tier) if feed_tier else None,
                timeout_sec=timeout_sec,
            )
            if doc_id:
                new_count += 1
                if got_full:
                    fulltext_count += 1
            elif was_skipped:
                skipped += 1
            if new_count + skipped >= max_items:
                break

        if not page_has_articles:
            break
        if new_count + skipped >= max_items:
            break
        if page_no >= max_pages:
            break

    if not seen:
        return new_count, skipped, fulltext_count, "empty_all_pages"
    return new_count, skipped, fulltext_count, None


def ingest_policy_feeds(*, timeout_sec: float = 20.0) -> dict[str, Any]:
    """拉取 HTML/RSS 列表 → doc_registry（可选全文）· 失败 feed 记 errors 不 mock。"""
    cfg = _load_feeds_cfg()
    policy_t0 = _load_policy_t0_cfg()
    feeds = cfg.get("feeds") or []
    max_items = int(cfg.get("max_items_per_feed") or policy_t0.get("max_items_per_feed") or 20)
    lookback_days = int(cfg.get("lookback_days") or 730)
    fetch_full_text = bool(cfg.get("fetch_full_text", policy_t0.get("fetch_full_text", False)))
    full_text_max = int(cfg.get("full_text_max_chars") or policy_t0.get("full_text_max_chars") or 48000)
    min_full_text = int(cfg.get("min_full_text_chars") or policy_t0.get("min_full_text_chars") or 200)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)

    new_count = 0
    skipped = 0
    fulltext_count = 0
    errors: list[str] = []

    for feed in feeds:
        feed_id = str(feed.get("id") or "unknown")
        url = str(feed.get("url") or "").strip()
        if not url:
            errors.append(f"{feed_id}:empty_url")
            continue
        kind = str(feed.get("kind") or "rss").lower()
        try:
            if kind == "html_list":
                feed_new, feed_skipped, feed_ft, err = _ingest_html_list_feed(
                    feed,
                    max_items=max_items,
                    cutoff=cutoff,
                    timeout_sec=timeout_sec,
                    fetch_full_text=fetch_full_text,
                    full_text_max=full_text_max,
                    min_full_text=min_full_text,
                )
            elif kind == "api_paginated":
                feed_new, feed_skipped, feed_ft, err = _ingest_api_paginated_feed(
                    feed,
                    max_items=max_items,
                    cutoff=cutoff,
                    timeout_sec=timeout_sec,
                    fetch_full_text=fetch_full_text,
                    full_text_max=full_text_max,
                    min_full_text=min_full_text,
                )
            else:
                feed_new, feed_skipped, feed_ft, err = _ingest_rss_feed(
                    feed,
                    max_items=max_items,
                    cutoff=cutoff,
                    timeout_sec=timeout_sec,
                    fetch_full_text=fetch_full_text,
                    full_text_max=full_text_max,
                    min_full_text=min_full_text,
                )
            new_count += feed_new
            skipped += feed_skipped
            fulltext_count += feed_ft
            if err:
                errors.append(f"{feed_id}:{err}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("政策采集失败 %s: %s", feed_id, exc)
            errors.append(f"{feed_id}:{exc}")

    status = "ok" if (new_count > 0 or skipped > 0 or not errors) else "error"
    if status == "error" and not errors:
        errors.append("all_feeds_empty")

    return {
        "status": status if new_count > 0 or skipped > 0 else ("ok" if not errors else "error"),
        "detail": None if new_count > 0 else "无新增政策文档（可能已入库或源空/不可达）",
        "new_count": new_count,
        "skipped": skipped,
        "fulltext_count": fulltext_count,
        "fetch_full_text": fetch_full_text,
        "feed_count": len(feeds),
        "errors": errors[:10],
        "source": "deepsea:policy_ingest",
    }
