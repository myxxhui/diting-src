"""Lighthouse 场景基类：统一 prompt 拼装 + AIDispatcher 调用 + JSON 解析。

所有 5 场景共享：
  - dispatcher.call() 统一入口（共享规约 19）
  - JSON 鲁棒解析（容忍 ```json fence 与前后噪音）
  - CallMetadata 自动生成
  - dry_run 路由（无 ANTHROPIC_API_KEY 时不打远程）

[Ref: 共享规约 19 §SDK1]
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Literal

from apps.common.ai_dispatcher import AIDispatcher, AIResponse, Scene
from apps.deep_strike.lighthouse.schemas import CallMetadata

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)
_FIRST_JSON_OBJ = re.compile(r"\{[\s\S]*\}")


def extract_json(text: str) -> dict:
    """从模型响应中稳健提取 JSON 对象。

    优先级：① ```json``` 围栏；② 首个 {...} 块；③ 整段。
    """
    text = text.strip()
    if not text:
        raise ValueError("空响应")

    fence = _JSON_FENCE.search(text)
    if fence:
        return json.loads(fence.group(1).strip())

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    obj = _FIRST_JSON_OBJ.search(text)
    if obj:
        return json.loads(obj.group(0))

    raise ValueError(f"未能从响应中提取 JSON: {text[:200]}")


class BaseLighthouseScene:
    """五场景共享基类。"""

    scene: Scene = "dry_run"  # 子类覆盖
    prompt_template_id: str = "base_v1"

    def __init__(
        self,
        dispatcher: AIDispatcher | None = None,
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> None:
        self.dispatcher = dispatcher or AIDispatcher.default()
        self.max_tokens = max_tokens
        self.temperature = temperature

    # ------------------------------------------------------------------
    # 子类钩子
    # ------------------------------------------------------------------

    def build_messages(self, payload: Any) -> list[dict[str, str]]:  # pragma: no cover
        raise NotImplementedError

    def parse(self, raw_json: dict, payload: Any, metadata: CallMetadata) -> Any:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 统一调用
    # ------------------------------------------------------------------

    def call(self, payload: Any, *, force_route: Literal["remote", "local", "mock"] | None = None) -> Any:
        messages = self.build_messages(payload)
        resp: AIResponse = self.dispatcher.call(
            scene=self.scene,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            force_route=force_route,
        )

        metadata = CallMetadata(
            model_name=resp.model,
            prompt_template_id=self.prompt_template_id,
            generated_at=datetime.utcnow(),
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_yuan_est=resp.cost_yuan_est,
            route=resp.route,
        )

        try:
            raw_json = extract_json(resp.text)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("[%s] JSON 解析失败，走 fallback: %s", self.scene, exc)
            return self.fallback(payload, metadata, reason=str(exc))

        try:
            return self.parse(raw_json, payload, metadata)
        except Exception as exc:
            logger.warning("[%s] parse 失败，走 fallback: %s", self.scene, exc)
            return self.fallback(payload, metadata, reason=str(exc))

    # ------------------------------------------------------------------
    # 降级
    # ------------------------------------------------------------------

    def fallback(self, payload: Any, metadata: CallMetadata, *, reason: str) -> Any:  # pragma: no cover
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 fallback（解析失败原因：{reason}）"
        )
