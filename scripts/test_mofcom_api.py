"""Test MOFCOM pagination API with same headers & session as _ingest_api_paginated_feed."""
import httpx, json, re, sys

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://www.mofcom.gov.cn/zwgk/zcfb/index.html',
}

with httpx.Client(headers=HEADERS) as client:
    # Warmup
    client.get("https://www.mofcom.gov.cn/zwgk/zcfb/index.html", timeout=15)
    print(f'Cookies: {dict(client.cookies)}')

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

    r = client.get(
        'https://www.mofcom.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit',
        params=params,
        timeout=30,
    )
    print(f'HTTP: {r.status_code}  Size: {len(r.text)}')

    if r.status_code == 200:
        body = r.text
        try:
            payload = json.loads(body) if body.strip().startswith('{') else {}
            if payload.get('success') and payload.get('data', {}).get('html'):
                body = payload['data']['html']
                print('Parsed JSON, extracted data.html')
        except (json.JSONDecodeError, TypeError, KeyError):
            print('Not JSON response')

        links = re.findall(r'href="([^"]+)"', body)
        art_links = [l for l in links if 'art_' in l]
        print(f'Article links: {len(art_links)}')
        for l in art_links[:5]:
            print(f'  {l[:120]}')
    else:
        print(f'Error: {r.text[:300]}')
