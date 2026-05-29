"""DVC 数据版本化封装。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
[DNA: _System_DNA/05_super_evo/dna_stage_1_启动期.yaml#tech_stack.version_control]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from apps.super_evo.config import settings


def _dvc_base() -> list[str]:
    """在用户目录 pip 安装时 `dvc` 常不在 PATH，统一用当前解释器调用。"""
    if shutil.which("dvc"):
        return ["dvc"]
    return [sys.executable, "-m", "dvc"]
class DVCError(RuntimeError):
    """DVC 命令执行失败抛出。"""


class DVCManager:
    """对 dvc CLI 的最小可用封装。

    用途：
    - init: 在 training/ 子目录初始化 dvc
    - configure_remote: 把 MinIO 配为 dvc 远程
    - add: dvc add path 并把 .dvc 文件 git add
    - commit: git add + git commit
    - get_current_version: HEAD 短 SHA
    """

    def __init__(self, repo_path: Path | str | None = None) -> None:
        self.repo_path = Path(repo_path or settings.dvc_repo_path)
        self.repo_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _run(cmd: list[str], cwd: Path) -> str:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise DVCError(f"cmd={cmd} stderr={result.stderr.strip()}")
        return result.stdout.strip()

    def is_initialized(self) -> bool:
        return (self.repo_path / ".dvc").exists()

    def init(self, no_scm: bool = True) -> None:
        if self.is_initialized():
            return
        cmd = _dvc_base() + ["init"]
        if no_scm:
            cmd.append("--no-scm")
        self._run(cmd, cwd=self.repo_path)

    def _remote_names(self) -> set[str]:
        try:
            out = self._run(_dvc_base() + ["remote", "list"], cwd=self.repo_path)
        except DVCError:
            return set()
        names: set[str] = set()
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if parts:
                names.add(parts[0])
        return names

    def configure_remote(
        self,
        name: str | None = None,
        url: str | None = None,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> str:
        name = name or settings.dvc_remote_name
        url = url or f"s3://{settings.minio_bucket}/dvc-store"
        endpoint = endpoint or settings.minio_endpoint
        access_key = access_key or settings.minio_access_key
        secret_key = secret_key or settings.minio_secret_key

        if name not in self._remote_names():
            self._run(_dvc_base() + ["remote", "add", "-d", "-f", name, url], cwd=self.repo_path)
        else:
            self._run(_dvc_base() + ["remote", "modify", name, "url", url], cwd=self.repo_path)

        self._run(
            _dvc_base() + ["remote", "modify", name, "endpointurl", endpoint],
            cwd=self.repo_path,
        )
        self._run(
            _dvc_base() + ["remote", "modify", name, "access_key_id", access_key],
            cwd=self.repo_path,
        )
        self._run(
            _dvc_base() + ["remote", "modify", name, "secret_access_key", secret_key],
            cwd=self.repo_path,
        )
        return name

    def add(self, paths: Iterable[str | Path]) -> list[str]:
        added: list[str] = []
        for p in paths:
            self._run(_dvc_base() + ["add", str(p)], cwd=self.repo_path)
            added.append(str(p))
        return added

    def push(self, remote: str | None = None) -> str:
        cmd = _dvc_base() + ["push"]
        if remote:
            cmd.extend(["-r", remote])
        return self._run(cmd, cwd=self.repo_path)

    def pull(self, remote: str | None = None) -> str:
        cmd = _dvc_base() + ["pull"]
        if remote:
            cmd.extend(["-r", remote])
        return self._run(cmd, cwd=self.repo_path)

    def health(self) -> dict:
        try:
            subprocess.run(
                _dvc_base() + ["version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            return {"ok": False, "reason": "dvc CLI not available"}
        if not self.is_initialized():
            return {"ok": False, "reason": "dvc not initialized in repo"}
        try:
            remotes = self._run(_dvc_base() + ["remote", "list"], cwd=self.repo_path)
        except DVCError as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": True, "repo": str(self.repo_path), "remotes": remotes.splitlines()}
