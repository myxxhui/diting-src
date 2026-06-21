"""Test MOFCOM pagination API to extract all policy article links."""
import httpx, json, re, sys

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://www.mofcom.gov.cn/zwgk/zcfb/index.html',
}

BASE = 'https://www.mofcom.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit'

# Try to get total page count first
params_p1 = {
    'parseType': 'bulidstatic',
    'webId': '8f43c7ad3afc411fb56f281724b73708',
    'tplSetId': '52551ea0e2c14bca8c84792f7aa37ead',
    'pageType': 'column',
    'tagId': '分页列表',
    'editType': 'null',
    'pageId': 'fc8bdff48fa345a48b651c1285b70b8f',
    'paramJson': json.dumps({'pageNo': 1, 'pageSize': 15}, separators=(',', ':')),
}

r = httpx.get(BASE, params=params_p1, headers=HEADERS, timeout=30)
print(f'HTTP: {r.status_code}  Size: {len(r.text)} chars')

# Extract total pages
total_pages = 154  # default from UI observation
# Try to find in response
for pat in [r'pageCount\s*[=:]\s*(\d+)', r'"totalPages"\s*:\s*(\d+)', r'totalCount\s*[=:]\s*(\d+)']:
    m = re.search(pat, r.text)
    if m:
        total_count = int(m.group(1))
        print(f'Found total: {total_count}')
        total_pages = total_count if 'Count' in pat else 0
        if total_pages == 0:
            total_pages = (total_count + 14) // 15
        break

# Extract links from page 1
links = set()
for m in re.finditer(r'href="([^"]*art_[^"]+)"', r.text):
    link = m.group(1)
    if not link.startswith('http'):
        link = 'https://www.mofcom.gov.cn' + link if link.startswith('/') else f'https://www.mofcom.gov.cn/{link}'
    links.add(link)

print(f'Page 1: {len(links)} unique links')

# Fetch remaining pages
for page_no in range(2, min(total_pages + 1, 500)):  # cap at 500
    params = {**params_p1, 'paramJson': json.dumps({'pageNo': page_no, 'pageSize': 15}, separators=(',', ':'))}
    try:
        r = httpx.get(BASE, params=params, headers=HEADERS, timeout=30)
        page_links = 0
        for m in re.finditer(r'href="([^"]*art_[^"]+)"', r.text):
            link = m.group(1)
            if not link.startswith('http'):
                link = 'https://www.mofcom.gov.cn' + link if link.startswith('/') else f'https://www.mofcom.gov.cn/{link}'
            links.add(link)
            page_links += 1
        if page_no % 20 == 0:
            print(f'  Page {page_no}: +{page_links} links, total unique: {len(links)}')
    except Exception as e:
        print(f'  Page {page_no} ERROR: {e}')
        break

print(f'\nTotal unique article links: {len(links)}')
for l in sorted(links)[:10]:
    print(f'  {l}')
for l in sorted(links)[-5:]:
    print(f'  {l}')

sys.exit(0)
