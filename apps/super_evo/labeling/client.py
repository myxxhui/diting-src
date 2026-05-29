"""Label Studio HTTP API 客户端封装。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md]
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LabelStudioError(RuntimeError):
    """Label Studio HTTP 调用失败。"""


class LabelStudioClient:
    """Label Studio 1.10+ HTTP API 封装。

    认证：环境变量 `SUPER_EVO_LS_USER_TOKEN`（与 compose 一致）。
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("SUPER_EVO_LS_URL", "http://localhost:8081")).rstrip("/")
        self.token = token or os.getenv("SUPER_EVO_LS_USER_TOKEN", "super-evo-token-dev")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, base_url=self.base_url, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
        }

    def health(self) -> dict[str, Any]:
        try:
            r = self._client.get("/version")
            r.raise_for_status()
            body = r.json()
            return {"ok": True, "version": body.get("release") or body}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def list_projects(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/projects", params={"page_size": "100"})
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and "results" in body:
            return list(body["results"])
        if isinstance(body, list):
            return body
        return []

    def get_project_by_title(self, title: str) -> dict[str, Any] | None:
        for p in self.list_projects():
            if p.get("title") == title:
                return p
        return None

    def create_project(self, title: str, label_config: str, description: str = "") -> dict[str, Any]:
        existing = self.get_project_by_title(title)
        if existing:
            logger.info("project exists, reuse id=%s", existing["id"])
            return existing
        r = self._client.post(
            "/api/projects",
            json={"title": title, "label_config": label_config, "description": description},
        )
        if r.status_code >= 400:
            raise LabelStudioError(f"create_project failed: {r.status_code} {r.text[:200]}")
        return r.json()

    def import_tasks(self, project_id: int, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post(f"/api/projects/{project_id}/import", json=tasks)
        if r.status_code >= 400:
            raise LabelStudioError(f"import_tasks failed: {r.status_code} {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError:
            return {"raw": r.text}

    def export_annotations(self, project_id: int, fmt: str = "JSON") -> list[dict[str, Any]]:
        r = self._client.get(f"/api/projects/{project_id}/export", params={"exportType": fmt})
        if r.status_code >= 400:
            raise LabelStudioError(f"export failed: {r.status_code} {r.text[:200]}")
        try:
            data = r.json()
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def get_task_count(self, project_id: int) -> int:
        r = self._client.get(f"/api/projects/{project_id}")
        r.raise_for_status()
        return int(r.json().get("task_number") or 0)

    def close(self) -> None:
        self._client.close()


def load_template(name: str) -> str:
    base = Path(__file__).resolve().parent / "task_templates"
    p = base / f"{name}.xml"
    if not p.exists():
        raise FileNotFoundError(f"template not found: {p}")
    return p.read_text(encoding="utf-8")
