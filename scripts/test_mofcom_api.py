"""Test MOFCOM pagination API to extract policy article links."""
import httpx, json, re, sys

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://www.mofcom.gov.cn/zwgk/zcfb/index.html',
}

BASE = 'https://www.mofcom.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit'

params = {
    'parseType': 'bulidstatic',
    'webId': '8f43c7ad3afc411fb56f281724b73708',
    'tplSetId': '52551ea0e2c14bca8c84792f7aa37ead',
    'pageType': 'column',
    'tagId': '分页列表',
    'editType': 'null',
    'pageId': 'fc8bdff48fa345a48b651c1285b70b8f',
    'paramJson': '{"pageNo":1,"pageSize":"15"}',
}

r = httpx.get(BASE, params=params, headers=HEADERS, timeout=30)
print(f'HTTP: {r.status_code}  Size: {len(r.text)}')

if r.status_code == 200:
    links = re.findall(r'href="([^"]+)"', r.text)
    art_links = [l for l in links if 'art_' in l]
    print(f'Article links: {len(art_links)}')
    for l in art_links[:5]:
        print(f'  {l[:120]}')
    
    # also check total pages
    for m in re.finditer(r'pageCount|totalPages|totalCount', r.text):
        ctx = r.text[max(0, m.start()-20):m.end()+20]
        print(f'Pagination context: ...{ctx}...')
else:
    print(f'Error: {r.text[:500]}')
