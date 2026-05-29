"""Anthropic Claude API 客户端封装（D5 Teacher 专用）。

包含：
- 模型选择：TEACHER_MODEL > ANTHROPIC_MODEL > 默认 claude-sonnet-4-5
  （Teacher 批量蒸馏用 sonnet 级；Lighthouse 高推理用 LIGHTHOUSE_REMOTE_MODEL）
- 指数退避重试（429 / 5xx / 网络错误）
- dry_run 模式（无 key 时返回 mock 响应）

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
[Ref: _System_DNA/02_deep_strike/dna_deep_strike_theme_sniffer.yaml::remote_large_model]
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)


class TeacherAPIError(RuntimeError):
    """Teacher API 失败（已重试过最大次数）。"""


class TransientAPIError(RuntimeError):
    """可重试的瞬时错误（429 / 5xx / 网络）。"""


@dataclass
class TeacherResponse:
    text: str
    raw: dict
    model: str


class AnthropicTeacherClient:
    """Anthropic Claude 客户端（Lighthouse-Alpha 远程脑力 + D5 Teacher 共用）。

    模型优先级：构造参数 > ANTHROPIC_MODEL 环境变量 > DEFAULT_MODEL
    默认使用 claude-opus-4-6（实测可用 slug，对应 DNA Y01 Opus 4.7）。

    使用 anthropic SDK；如 ANTHROPIC_API_KEY 未设置则进入 dry_run 模式。
    """

    # TEACHER_MODEL 优先（Teacher 批量蒸馏用 sonnet 级，省成本）
    # 未设 TEACHER_MODEL 时回退 ANTHROPIC_MODEL，最终兜底 claude-sonnet-4-5
    DEFAULT_MODEL = os.getenv("TEACHER_MODEL") or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        max_attempts: int = 4,
        dry_run: bool | None = None,
    ) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.dry_run = dry_run if dry_run is not None else not bool(self.api_key)
        self._client = None
        if not self.dry_run:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise RuntimeError("anthropic SDK 未安装；pip install anthropic") from exc
            self._client = AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)

    @property
    def model_name(self) -> str:
        return self.model

    async def chat(self, messages: list[dict[str, str]]) -> TeacherResponse:
        """发送 chat 请求，自动指数退避重试。

        messages 第一条若为 system 会被提取为 system 参数；其余按 user/assistant 顺序传入。
        """
        if self.dry_run:
            return self._dry_run_response(messages)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_random_exponential(multiplier=1, max=20),
            retry=retry_if_exception_type(TransientAPIError),
            reraise=True,
        ):
            with attempt:
                return await self._call_once(messages)

        raise TeacherAPIError("unreachable")

    async def _call_once(self, messages: list[dict[str, str]]) -> TeacherResponse:
        system = ""
        user_msgs: list[dict[str, str]] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_msgs.append(m)
        try:
            resp = await self._client.messages.create(  # type: ignore[union-attr]
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=user_msgs,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in {429} or (
                status is not None and isinstance(status, int) and 500 <= status < 600
            ):
                raise TransientAPIError(f"{type(exc).__name__}: {exc}") from exc
            msg = str(exc).lower()
            if "timeout" in msg or "connection" in msg or "connect" in msg:
                raise TransientAPIError(f"{type(exc).__name__}: {exc}") from exc
            raise TeacherAPIError(str(exc)) from exc

        text = ""
        try:
            text = resp.content[0].text  # type: ignore[index, union-attr]
        except Exception:
            text = json.dumps(resp.model_dump() if hasattr(resp, "model_dump") else {})
        return TeacherResponse(
            text=text,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
            model=self.model,
        )

    def _dry_run_response(self, messages: list[dict[str, str]]) -> TeacherResponse:
        """dry_run：根据 user 消息内容产生确定性 mock JSON 返回。"""
        user_text = " ".join(m["content"] for m in messages if m["role"] != "system")
        mock = {
            "risk_score": 0.5,
            "decision": "degrade",
            "evidence": ["[dry_run] no real API call"],
            "reasoning": "dry_run 模式默认返回 degrade，置信度低。",
            "confidence": 0.3,
            "_dry_run_input_hash": hash(user_text) & 0xFFFFFFFF,
        }
        return TeacherResponse(text=json.dumps(mock, ensure_ascii=False), raw=mock, model="dry-run")
