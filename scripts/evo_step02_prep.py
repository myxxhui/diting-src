"""D5 step02 prep：打印双模型分配状态。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02 §8]
"""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(__file__).parents[1] / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        # python-dotenv 未安装时手动简单解析
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    _load_dotenv()
    teacher = os.getenv("TEACHER_MODEL") or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    lighthouse = os.getenv("LIGHTHOUSE_REMOTE_MODEL") or os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    has_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    print(f"  TEACHER_MODEL    = {teacher}")
    print(f"  LIGHTHOUSE_MODEL = {lighthouse}")
    print(f"  ANTHROPIC_KEY    = {'✅ 已配置' if has_key else '⚠️  未配置（dry_run 模式）'}")

    assert teacher, "TEACHER_MODEL / ANTHROPIC_MODEL 均未设置"
    assert lighthouse, "LIGHTHOUSE_REMOTE_MODEL / ANTHROPIC_MODEL 均未设置"
    print("  ✅ 双模型分配配置自检通过")


if __name__ == "__main__":
    main()
