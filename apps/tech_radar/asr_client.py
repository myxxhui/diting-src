"""技术雷达 · ASR 客户端：对接阿里云 DashScope 通义听悟语音转写

前置条件：
  - pip install dashscope>=1.22
  - 环境变量 DASHSCOPE_API_KEY 已设置

费用：
  - 实时转写：¥0.016/分钟（按音频时长计费）
  - 详细计费：https://help.aliyun.com/zh/dashscope/product-overview/billing

API 文档：
  - Recognition 初始化：model, callback, format, sample_rate（必填）
  - Recognition.call(file)：读取本地文件，同步返回转写结果
"""
from __future__ import annotations

from pathlib import Path

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult


class _NullCallback(RecognitionCallback):
    """占位回调，用于同步模式（call() 直接从返回值拿结果）"""

    def on_open(self):
        pass

    def on_complete(self):
        pass

    def on_error(self, result: RecognitionResult):
        pass

    def on_close(self):
        pass

    def on_event(self, result: RecognitionResult):
        pass


def transcribe_sync(
    audio_path: str | Path,
    api_key: str,
    model: str = "paraformer-realtime-v2",
) -> str:
    """同步转写：读取本地音频文件，调用 DashScope ASR，返回完整文本。

    Args:
        audio_path: 音频文件路径（.mp3）
        api_key: DashScope API Key
        model: ASR 模型，默认 paraformer-realtime-v2（中英双语实时转写）

    Returns:
        转写文本（拼接所有句子的完整文字）

    Raises:
        FileNotFoundError: 音频文件不存在
        RuntimeError: API 调用失败
    """
    dashscope.api_key = api_key

    recognizer = Recognition(
        model=model,
        callback=_NullCallback(),
        format="mp3",
        sample_rate=16000,
        disfluency_removal_enabled=True,
    )

    result = recognizer.call(
        file=str(audio_path),
    )

    if result.status_code != 200:
        raise RuntimeError(
            f"ASR 转写失败 (HTTP {result.status_code}): {result.message}"
        )

    sentences = result.get_sentence()
    if isinstance(sentences, list):
        return "".join(s.get("text", "") for s in sentences)
    elif isinstance(sentences, dict):
        return sentences.get("text", "")
    return ""
