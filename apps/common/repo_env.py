"""加载 diting-src 根目录 `.env` 到 os.environ（不覆盖已 export 的变量）."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """diting-src 仓库根（含 .env / Makefile）。"""
    return Path(__file__).resolve().parents[2]


def load_repo_dotenv(root: Path | None = None) -> bool:
    """加载 ``{root}/.env``；成功返回 True，无文件返回 False。"""
    root = root or repo_root()
    env_file = root / ".env"
    if not env_file.is_file():
        return False
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    except ImportError:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
    return True


def anthropic_key_configured() -> bool:
    """是否已配置 Teacher / Lighthouse 用的 Anthropic Key（读 .env 后调用）。"""
    return bool(
        os.environ.get("ANTHROPIC_API_KEY", "").strip()
        or os.environ.get("CRYO_TEACHER_API_KEY", "").strip()
    )
