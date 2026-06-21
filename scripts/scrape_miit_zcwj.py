"""Scrape MIIT zcwj page with Playwright to find API."""
from playwright.sync_api import sync_playwright
import sys

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    api_calls = set()
    def capture(req):
        url = req.url
        if any(k in url.lower() for k in ['api', 'json', 'callback', 'data/list', 'page/build']):
            api_calls.add(url[:200])
    page.on('request', capture)

    page.goto('https://www.miit.gov.cn/zwgk/zcwj/wjfb/index.html', timeout=30000, wait_until='networkidle')
    page.wait_for_timeout(5000)

    print(f'Total captured API calls: {len(api_calls)}')
    for u in sorted(api_calls):
        print(f'  {u}')

    # Get all article links
    links = page.evaluate('() => Array.from(document.querySelectorAll("a[href]")).map(a => [a.href, a.textContent.trim()])')
    art_links = [(h,t) for h,t in links if '/art/' in h and 'miit.gov.cn' in h and len(t) > 10]
    print(f'\nArticle links: {len(art_links)}')
    for h, t in art_links[:15]:
        print(f'  [{t[:60]}] -> {h[:120]}')

    browser.close()
