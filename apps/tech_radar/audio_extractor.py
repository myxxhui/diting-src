"""技术雷达 · 音频提取器：ffmpeg 视频 → 音频降维"""
from __future__ import annotations

import subprocess
from pathlib import Path


def extract_audio(mp4_path: str | Path, mp3_path: str | Path) -> str:
    """ffmpeg 剥离视频轨道，输出 16kHz 单声道 mp3。

    Args:
        mp4_path: 输入视频文件路径
        mp3_path: 输出音频文件路径

    Returns:
        输出音频文件路径

    Raises:
        RuntimeError: ffmpeg 执行失败
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(mp4_path),
        "-vn",                    # 丢弃视频轨道
        "-ac", "1",              # 单声道
        "-ar", "16000",          # 16kHz 采样率
        "-ab", "64k",            # 64kbps 码率
        str(mp3_path),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 执行失败 (exit={result.returncode})")

    if not Path(mp3_path).exists():
        raise RuntimeError(f"ffmpeg 未生成输出文件: {mp3_path}")

    return str(mp3_path)


def get_audio_duration_sec(audio_path: str | Path) -> float:
    """用 ffprobe 获取音频时长（秒）。

    Returns:
        时长，秒。失败时返回 0.0。
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def get_video_duration_sec(video_path: str | Path) -> float:
    """用 ffprobe 直接获取视频时长（秒），无需先提取音频。

    用于快速过滤过短视频（广告/片段）。
    """
    return get_audio_duration_sec(video_path)  # ffprobe 对视频文件同样有效
