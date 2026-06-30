"""技术雷达 · 配置管理
优先从 workspace 根目录 (~/Desktop/workspace/.env) 加载配置，
数据文件（原始视频/文本输出等）落在 TECH_RADAR_WORKSPACE 指定目录下。
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# .env 搜索路径（按优先级）
_ENV_SEARCH_PATHS = [
    Path.home() / "Desktop" / "workspace",
    Path.home() / "tech-radar-workspace",
]


def _load_env() -> None:
    """按优先级搜索并加载第一个存在的 .env"""
    for path in _ENV_SEARCH_PATHS:
        env_path = path / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            print(f"📄 加载配置: {env_path}")
            return
    print("⚠️  未找到 .env（搜索路径: {}），使用默认值".format(
        "; ".join(str(p) for p in _ENV_SEARCH_PATHS)
    ))


def _resolve_workspace() -> Path:
    """确定主工作目录（数据文件落在此目录下）

    优先级：
    1. 环境变量 TECH_RADAR_WORKSPACE
    2. 默认 ~/Desktop/workspace/tech-radar
    """
    env_val = os.getenv("TECH_RADAR_WORKSPACE")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return Path.home() / "Desktop" / "workspace" / "tech-radar"


def load_config(workspace_dir: str | Path | None = None) -> dict:
    """加载配置字典。

    Args:
        workspace_dir: 显式指定工作目录（调试用），
                       不传则从 .env 或默认路径读取。

    Returns:
        {
            "dashscope_api_key": str,
            "daily_budget_minutes": int,
            "cost_per_minute": float,
            "min_duration_sec": int,
            "video_dir": str,
            "audio_dir": str,
            "output_dir": str,
            "state_file": str,
            "workspace_dir": str,
        }
    """
    # 先加载 .env（这样 .env 里的 TECH_RADAR_WORKSPACE 也能生效）
    if workspace_dir is None:
        _load_env()

    # 确定工作目录
    if workspace_dir is not None:
        primary = Path(workspace_dir).expanduser().resolve()
    else:
        primary = _resolve_workspace()

    print(f"📂 文件目录: {primary}")

    config = {
        # API
        "dashscope_api_key": os.getenv("DASHSCOPE_API_KEY", ""),

        # 预算
        "daily_budget_minutes": int(os.getenv("DAILY_BUDGET_MINUTES", "60")),
        "cost_per_minute": float(os.getenv("ASR_COST_PER_MINUTE", "0.016")),

        # 过滤
        "min_duration_sec": int(os.getenv("MIN_VIDEO_DURATION_SEC", "30")),

        # 目录（相对主工作目录）
        "video_dir": str(primary / os.getenv("VIDEO_DIR", "原始视频")),
        "audio_dir": str(primary / os.getenv("AUDIO_DIR", "音频缓冲")),
        "output_dir": str(primary / os.getenv("OUTPUT_DIR", "文本输出")),
        "state_file": str(primary / ".pipeline_state.json"),

        # 透传
        "workspace_dir": str(primary),
    }

    # 验证
    if not config["dashscope_api_key"]:
        print("⚠️  DASHSCOPE_API_KEY 未设置。ASR 转写功能将不可用。")

    return config
