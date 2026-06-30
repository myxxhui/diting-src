"""技术雷达 · 去重与过滤：文件 hash 去重 + 时长过滤"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path


def compute_quick_hash(filepath: str | Path) -> str:
    """快速文件指纹：前 1MB SHA256[:16] + 文件大小。

    16 字符 hash + 文件大小作为后缀，碰撞概率可忽略。
    相比全文件 hash，处理大视频时快 10-100 倍。
    """
    size = os.path.getsize(filepath)
    with open(filepath, "rb") as f:
        head = f.read(1024 * 1024)  # 前 1MB
    return f"{hashlib.sha256(head).hexdigest()[:16]}:{size}"


# ── 状态管理（JSON 持久化）───────────────────────────────────────────────

class PipelineState:
    """处理状态管理器，读写 .pipeline_state.json。

    每个条目结构：
    {
        "<file_hash>": {
            "status": "completed|skipped|failed",
            "date": "2026-06-29",
            "duration_minutes": 15.5,
            "source_file": "xxx.mp4",
            "error": "<optional error message>"
        }
    }
    """

    def __init__(self, state_file: str | Path):
        self._path = Path(state_file)
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def is_processed(self, file_hash: str) -> bool:
        """是否已处理完成"""
        entry = self._data.get(file_hash)
        return entry is not None and entry.get("status") in ("completed", "skipped")

    def mark(self, file_hash: str, status: str, **extra):
        """标记文件处理状态"""
        self._data[file_hash] = {
            "status": status,
            "date": date.today().isoformat(),
            **extra,
        }
        self._save()

    def get_today_usage(self) -> float:
        """获取今日已累计的 ASR 处理时长（分钟）"""
        today = date.today().isoformat()
        return sum(
            entry.get("duration_minutes", 0)
            for entry in self._data.values()
            if entry.get("date") == today
            and entry.get("status") == "completed"
        )

    def summary(self) -> str:
        """打印处理统计"""
        total = len(self._data)
        completed = sum(1 for v in self._data.values() if v["status"] == "completed")
        skipped = sum(1 for v in self._data.values() if v["status"] == "skipped")
        failed = sum(1 for v in self._data.values() if v["status"] == "failed")
        today_usage = self.get_today_usage()
        return (
            f"📊 处理统计：总计 {total} 个文件 "
            f"（✅ {completed} | ⏭️  {skipped} | ❌ {failed}）"
            f" | 今日 ASR 使用 {today_usage:.0f} 分钟"
        )
