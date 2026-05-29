"""MinIO 客户端与 DVC 管理器单元测试。

注：需要 docker compose up 后运行；如 MinIO 不可达自动 skip。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
"""

from __future__ import annotations

import io
import subprocess
import sys

import pytest

from apps.super_evo.storage.minio_client import MinIOClient
from apps.super_evo.versioning.dvc_manager import DVCManager


@pytest.fixture(scope="module")
def minio() -> MinIOClient:
    client = MinIOClient(bucket="super-evo-test")
    health = client.health()
    if not health.get("ok"):
        pytest.skip(f"MinIO not reachable: {health}")
    return client


def test_minio_upload_download_bytes(minio: MinIOClient):
    payload = b"hello-super-evo"
    key = "tests/hello.txt"
    minio.upload_bytes(payload, key)

    got = minio.download_bytes(key)
    assert got == payload


def test_minio_list_keys(minio: MinIOClient):
    keys = minio.list_keys(prefix="tests/")
    assert any(k.startswith("tests/") for k in keys)


def test_minio_upload_fileobj(minio: MinIOClient):
    fp = io.BytesIO(b"fileobj-payload")
    key = "tests/fileobj.txt"
    minio.upload_fileobj(fp, key)
    assert minio.download_bytes(key) == b"fileobj-payload"


def test_dvc_health_reports_initialized():
    try:
        subprocess.run(
            [sys.executable, "-m", "dvc", "version"],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except Exception:
        pytest.skip("dvc not runnable")
    m = DVCManager()
    health = m.health()
    assert "ok" in health
