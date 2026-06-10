"""鸿海 IR 月营收简报 · Playwright 渲染抓取 pr_raw_text。

[Ref: 28_ §2.2 fii_twse_cloud · Playwright]
"""
from __future__ import annotations

import logging
import re
from typing import Any

from apps.copilot.modules.executing.l3.fii_twse_cloud.constants import HONHAI_MONTHLY_CATEGORY_PATH

logger = logging.getLogger(__name__)

_BASE = "https://www.honhai.com"
_TIMEOUT_MS = 45_000

_NAV_MARKERS = (
    "關於鴻海",
    "投資人關係",
    "加入我們",
    "隱私權",
    "Cookie",
    "HHTD",
    "社群平台",
    "公司治理",
)
_REVENUE_MARKERS = (
    "自結合併營收",
    "營收摘要",
    "云端网路",
    "雲端網路",
    "消费智能",
    "消費智能",
    "电脑终端",
    "電腦終端",
    "元件及其他",
    "月增",
    "年增",
)


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


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _score_revenue_text(text: str) -> int:
    score = sum(2 for m in _REVENUE_MARKERS if m in text)
    score -= sum(3 for m in _NAV_MARKERS if m in text)
    if re.search(r"公告\d{4}年\d{2}月", text):
        score += 5
    if re.search(r"(云端|雲端).{0,8}(产品|產品)", text):
        score += 4
    return score


def _is_nav_noise(text: str) -> bool:
    return _score_revenue_text(text) < 3 and len(text) > 500


def _extract_from_dom(page: Any) -> str:
    """优先取含营收关键词的正文块，过滤全站导航。"""
    js = """
    () => {
      const markers = ['自結合併營收', '營收摘要', '云端网路', '雲端網路', '消费智能'];
      const nav = ['關於鴻海', '投資人關係', '加入我們', 'Cookie'];
      const score = (t) => {
        let s = 0;
        for (const m of markers) if (t.includes(m)) s += 2;
        for (const n of nav) if (t.includes(n)) s -= 3;
        if (/公告\\d{4}年\\d{2}月/.test(t)) s += 5;
        return s;
      };
      const selectors = [
        'article', '.article-content', '.news-content', '.detail-content',
        '[class*="press"]', '[class*="article"]', 'main'
      ];
      let best = '';
      let bestScore = -999;
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          const t = (el.innerText || '').trim();
          if (t.length < 80) continue;
          const s = score(t);
          if (s > bestScore) { bestScore = s; best = t; }
        }
      }
      if (bestScore >= 3) return best;
      const paras = Array.from(document.querySelectorAll('p, li, h2, h3'))
        .map(el => (el.innerText || '').trim())
        .filter(t => t.length > 20 && score(t) >= 2);
      if (paras.length) return paras.join('\\n\\n');
      return (document.body.innerText || '').trim();
    }
    """
    return _clean_text(page.evaluate(js))


def _refine_segment_text(text: str) -> str:
    """保留含板块/营收关键词的段落。"""
    if not text:
        return ""
    paras = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    keyed = [
        p
        for p in paras
        if re.search(
            r"營收|营收|雲端|云端|產品|产品|MoM|月增|年增|自結|合并|合併|方面",
            p,
        )
    ]
    if keyed:
        return "\n\n".join(keyed)
    return text


def fetch_monthly_pr_text_playwright(*, year: int, month: int) -> dict[str, Any]:
    """Playwright 打开鸿海 IR 月报页 · 提取正文（含 CSR 渲染后的 DOM 文本）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright 未安装") from exc

    title_needle = f"公告{year}年{month:02d}月自結合併營收"
    cat_url = f"{_BASE}{HONHAI_MONTHLY_CATEGORY_PATH}"
    article_id: int | None = None
    article_url: str | None = None
    pr_raw_text = ""
    img_urls: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(
                locale="zh-TW",
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(_TIMEOUT_MS)

            page.goto(cat_url, wait_until="networkidle")
            link = page.get_by_text(title_needle, exact=False).first
            if link.count() == 0:
                link = page.get_by_text(re.compile(rf"{year}年{month:02d}月.*自結合併營收")).first

            month_names = (
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            )
            month_en = month_names[month - 1] if 1 <= month <= 12 else ""
            img_pat = re.compile(rf"Monthly_Revenue_Report_{month_en}_{year}", re.I)

            def _probe_article(aid: int) -> bool:
                nonlocal article_url, article_id, html, img_urls, pr_raw_text
                probe = f"{_BASE}/zh-tw/press-center/press-releases/latest-news/{aid}"
                page.goto(probe, wait_until="networkidle")
                html = page.content()
                if not img_pat.search(html) and title_needle not in page.locator("body").inner_text():
                    return False
                article_url = probe
                article_id = aid
                img_urls = _extract_image_urls(html)
                raw = _extract_from_dom(page)
                pr_raw_text = _refine_segment_text(raw)
                return bool(pr_raw_text.strip()) and not _is_nav_noise(pr_raw_text)

            if link.count() > 0:
                href = link.evaluate(
                    "el => el.closest('a')?.href || el.querySelector('a')?.href || ''"
                )
                if href and re.search(r"latest-news/\d+", href):
                    article_url = str(href)
                    page.goto(article_url, wait_until="networkidle")
                    html = page.content()
                    img_urls = _extract_image_urls(html)
                    raw = _extract_from_dom(page)
                    pr_raw_text = _refine_segment_text(raw)
                else:
                    link.click()
                    page.wait_for_load_state("networkidle")
                    article_url = page.url
                    html = page.content()
                    img_urls = _extract_image_urls(html)
                    raw = _extract_from_dom(page)
                    pr_raw_text = _refine_segment_text(raw)

            if not article_url or _is_nav_noise(pr_raw_text) or not pr_raw_text.strip():
                pr_raw_text = ""
                for aid in range(2035, 1985, -1):
                    if _probe_article(aid):
                        break

        finally:
            browser.close()

    if not article_url:
        return {
            "pr_raw_text": "",
            "pr_image_urls": [],
            "article_id": None,
            "article_url": None,
            "source": "Hon Hai IR · Playwright",
            "playwright": True,
        }

    if article_id is None and article_url:
        m = re.search(r"latest-news/(\d+)", article_url)
        if m:
            article_id = int(m.group(1))

    if _is_nav_noise(pr_raw_text):
        logger.warning(
            "Playwright DOM 文本疑似导航/列表页(score=%d) · 清空待 OCR",
            _score_revenue_text(pr_raw_text),
        )
        pr_raw_text = ""

    return {
        "pr_raw_text": pr_raw_text.strip(),
        "pr_image_urls": img_urls,
        "article_id": article_id,
        "article_url": article_url,
        "source": "Hon Hai IR (honhai.com) · Playwright Chromium",
        "playwright": True,
        "dom_nav_noise": not bool(pr_raw_text.strip()),
    }
