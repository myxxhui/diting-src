"""MinIO 客户端封装。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
[DNA: _System_DNA/05_super_evo/dna_stage_1_启动期.yaml#tech_stack.storage]
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from apps.super_evo.config import settings


def _s3_client_config() -> Config:
    """MinIO 与本机 endpoint 通常需要 path-style。"""
    return Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    )


class MinIOClient:
    """super-evo 与 MinIO 的统一入口。

    用途：
    - 蒸馏 JSONL 上传 / 下载
    - LoRA 权重上传 / 下载
    - 一般性大文件存储

    所有方法对 bucket 不存在自动创建；对网络异常抛出明确错误。
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool | None = None,
    ) -> None:
        self.endpoint = endpoint or settings.minio_endpoint
        self.access_key = access_key or settings.minio_access_key
        self.secret_key = secret_key or settings.minio_secret_key
        self.bucket = bucket or settings.minio_bucket
        self.secure = settings.minio_secure if secure is None else secure

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=_s3_client_config(),
            region_name="us-east-1",
            use_ssl=self.secure,
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self._client.create_bucket(Bucket=self.bucket)
            else:
                raise

    def upload_file(self, local_path: str | Path, key: str) -> str:
        self.ensure_bucket()
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(local_path)
        self._client.upload_file(str(local_path), self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def upload_bytes(self, data: bytes, key: str) -> str:
        self.ensure_bucket()
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def upload_fileobj(self, fp: BinaryIO, key: str) -> str:
        self.ensure_bucket()
        self._client.upload_fileobj(fp, self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def download_file(self, key: str, local_path: str | Path) -> Path:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self.bucket, key, str(local_path))
        return local_path

    def download_bytes(self, key: str) -> bytes:
        buf = io.BytesIO()
        self._client.download_fileobj(self.bucket, key, buf)
        return buf.getvalue()

    def list_keys(self, prefix: str = "") -> list[str]:
        self.ensure_bucket()
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents") or []:
                keys.append(obj["Key"])
        return keys

    def health(self) -> dict:
        try:
            self.ensure_bucket()
            return {"ok": True, "bucket": self.bucket, "endpoint": self.endpoint}
        except (ClientError, EndpointConnectionError, OSError) as exc:
            return {"ok": False, "endpoint": self.endpoint, "reason": str(exc)}


def get_client() -> MinIOClient:
    return MinIOClient()
