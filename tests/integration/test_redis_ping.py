"""真实 Redis 连通性（与本机 super-evo / copilot 默认端口一致）。

无 Redis 时本文件中的用例会 **skip**（不判失败）。补全集成验证时：

```bash
docker run -d --rm --name diting-pytest-redis -p 6379:6379 redis:7-alpine
cd diting-src && python3 -m pytest tests/integration/test_redis_ping.py -v
docker stop diting-pytest-redis
```
"""

from __future__ import annotations

import pytest

REDIS_URL = "redis://localhost:6379/15"


@pytest.mark.asyncio
async def test_redis_ping_db15():
    try:
        import redis.asyncio as aioredis
    except ImportError:
        pytest.skip("redis.asyncio 不可用")

    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1.5)
        pong = await r.ping()
        await r.aclose()
    except Exception:
        pytest.skip(
            "未检测到可连 Redis（localhost:6379）。"
            "集成补测：docker run -d --rm --name diting-pytest-redis -p 6379:6379 redis:7-alpine"
        )
    assert pong is True


def test_super_evo_health_redis_component_when_redis_up():
    """在 Redis 可用时，super-evo /health 中 redis 组件应为 ok。"""
    try:
        import redis as sync_redis
    except ImportError:
        pytest.skip("redis 不可用")

    try:
        r = sync_redis.Redis(host="localhost", port=6379, db=5, socket_connect_timeout=1.5)
        r.ping()
        r.close()
    except Exception:
        pytest.skip("Redis 未就绪，跳过 super-evo 集成断言")

    from fastapi.testclient import TestClient

    from apps.super_evo.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["components"]["redis"]["ok"] is True
    # minio / dvc 未起时整体可为 degraded，不强制全绿
