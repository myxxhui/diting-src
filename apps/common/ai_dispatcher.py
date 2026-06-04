"""AIDispatcher — Lighthouse-Alpha 统一 AI 调度入口。

所有 Lighthouse 场景（The Scorer / The Critic / The Architect / The Timer / ETL）
**必须**通过 `AIDispatcher.call()` 发起模型请求，禁止直接调用 anthropic/openai SDK。

路由策略（共享规约 19 §三）：
  remote  → Claude Opus（LIGHTHOUSE_REMOTE_MODEL）：Scorer policy/mapping、Critic、Architect、Timer
  local   → Qwen-14B vLLM @ :8091：ETL 长文清洗、Scorer industry_space
  mock    → 本地确定性 mock（dry_run/CI）

环境变量（双模型分层）：
  ANTHROPIC_API_KEY            — Anthropic key（设置后 remote 路由可用）
  ANTHROPIC_BASE_URL           — 默认 https://api.anthropic.com
  LIGHTHOUSE_REMOTE_MODEL      — Lighthouse 高推理模型，默认 claude-opus-4-6
  ANTHROPIC_MODEL              — 兜底（未设 LIGHTHOUSE_REMOTE_MODEL 时读此值）
  AI_DISPATCHER_BUDGET_YUAN_DAILY — 每日软上限（元），超出拒绝 remote 调用；默认 1000
  VLLM_BASE_URL                — 本地 vLLM OpenAI 兼容接口；默认 http://localhost:8091/v1

[Ref: 03_原子目标与规约/_共享规约/19_异构AI调度栈规约.md §七]
[Ref: _System_DNA/02_deep_strike/dna_deep_strike_theme_sniffer.yaml::remote_large_model]
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

Scene = Literal[
    "scorer_policy",
    "scorer_mapping",
    "critic",
    "architect",
    "timer",
    "etl",
    "dry_run",
    "radar_assess",
    "radar_chat",
    "radar_distill",
]

Route = Literal["remote", "deepseek", "local", "mock"]

# 场景 → 路由映射（共享规约 19 §三）
_SCENE_ROUTE: dict[Scene, Route] = {
    "scorer_policy": "remote",
    "scorer_mapping": "remote",
    "critic": "remote",
    "architect": "remote",
    "timer": "remote",
    "etl": "local",
    "dry_run": "mock",
    "radar_assess": "remote",
    "radar_chat": "remote",
    "radar_distill": "deepseek",
}


@dataclass
class AIResponse:
    text: str
    model: str
    scene: str
    route: Route
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost_yuan_est: float = 0.0
    raw: dict = field(default_factory=dict)


class BudgetExceededError(RuntimeError):
    """单日预算软上限触发。"""


def _estimate_deepseek_cost_yuan(tokens_in: int, tokens_out: int) -> float:
    """DeepSeek 近似成本（元）· 可用 env 覆盖单价。"""
    usd_cny = float(os.getenv("RADAR_USD_CNY", "7.2"))
    in_m = float(os.getenv("RADAR_DEEPSEEK_IN_USD_PER_MTOK", "0.27"))
    out_m = float(os.getenv("RADAR_DEEPSEEK_OUT_USD_PER_MTOK", "1.10"))
    usd = (tokens_in / 1_000_000.0) * in_m + (tokens_out / 1_000_000.0) * out_m
    return round(usd * usd_cny, 4)


class AIDispatcher:
    """Lighthouse-Alpha 统一 AI 调度器（单实例推荐用 `default()` 工厂）。

    [Ref: 共享规约 19 SDK1 — AIDispatcher.call() 唯一入口]
    """

    _instance: AIDispatcher | None = None

    def __init__(
        self,
        *,
        anthropic_key: str | None = None,
        anthropic_base_url: str | None = None,
        anthropic_model: str | None = None,
        vllm_base_url: str | None = None,
        budget_yuan_daily: float | None = None,
    ) -> None:
        self._anthropic_key = (
            anthropic_key if anthropic_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
        )
        self._anthropic_base = anthropic_base_url or os.getenv(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )
        # Lighthouse remote 路由：优先 LIGHTHOUSE_REMOTE_MODEL，兜底 ANTHROPIC_MODEL
        self._anthropic_model = anthropic_model or (
            os.getenv("LIGHTHOUSE_REMOTE_MODEL")
            or os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")
        )
        self._vllm_base = vllm_base_url or os.getenv(
            "VLLM_BASE_URL", "http://localhost:8091/v1"
        )
        self._budget = (
            budget_yuan_daily if budget_yuan_daily is not None
            else float(os.getenv("AI_DISPATCHER_BUDGET_YUAN_DAILY", "1000"))
        )
        self._daily_spent: float = 0.0
        self._daily_date: str = ""
        self._anthropic_client: Any = None

        if self._anthropic_key:
            try:
                import anthropic  # noqa: PLC0415

                http_client: Any = None
                proxy = (os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip()
                if proxy:
                    import httpx  # noqa: PLC0415

                    http_client = httpx.Client(
                        proxy=proxy,
                        timeout=httpx.Timeout(120.0, connect=30.0),
                    )
                    logger.info("[AIDispatcher] Anthropic 客户端使用 HTTPS_PROXY")
                self._anthropic_client = anthropic.Anthropic(
                    api_key=self._anthropic_key,
                    base_url=self._anthropic_base,
                    **({"http_client": http_client} if http_client else {}),
                )
            except ImportError:
                logger.warning("anthropic SDK 未安装；remote 路由将不可用（pip install anthropic）")

    @classmethod
    def default(cls) -> "AIDispatcher":
        """全局单例，自动从环境变量初始化。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -------------------------------------------------------------------------
    # 公共 API
    # -------------------------------------------------------------------------

    def call(
        self,
        scene: Scene,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        force_route: Route | None = None,
        model_override: str | None = None,
    ) -> AIResponse:
        """统一调度入口。

        Args:
            scene:      调用场景，决定路由（共享规约 19 §三）
            messages:   OpenAI 格式 messages（system/user/assistant）
            max_tokens: 最大输出 token
            temperature: 采样温度
            force_route: 强制路由（测试 / 降级用）

        Returns:
            AIResponse

        Raises:
            BudgetExceededError: 日预算软上限触发
        """
        route = force_route or _SCENE_ROUTE.get(scene, "mock")

        self._check_budget()

        t0 = time.perf_counter()
        if route == "remote":
            resp = self._call_remote(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                model_override=model_override,
                scene=scene,
            )
        elif route == "deepseek":
            resp = self._call_deepseek(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                model_override=model_override,
                scene=scene,
            )
        elif route == "local":
            resp = self._call_local(messages, max_tokens=max_tokens, temperature=temperature)
        else:
            resp = self._call_mock(messages)

        latency_ms = int((time.perf_counter() - t0) * 1000)

        cost = 0.0
        if route in ("remote", "deepseek"):
            from apps.copilot.modules.radar.schema import estimate_cost_yuan

            if route == "deepseek":
                cost = _estimate_deepseek_cost_yuan(
                    resp.get("tokens_in", 0), resp.get("tokens_out", 0)
                )
            else:
                cost = estimate_cost_yuan(resp.get("tokens_in", 0), resp.get("tokens_out", 0))
            if cost <= 0:
                cost = 0.05 if route == "deepseek" else 0.5
            self._record_spend(cost)

        logger.info(
            "[AIDispatcher] scene=%s route=%s latency=%dms cost_est=¥%.2f",
            scene, route, latency_ms, cost,
        )

        return AIResponse(
            text=resp.get("text", ""),
            model=resp.get("model", "mock"),
            scene=scene,
            route=route,
            latency_ms=latency_ms,
            tokens_in=resp.get("tokens_in", 0),
            tokens_out=resp.get("tokens_out", 0),
            cost_yuan_est=cost,
            raw=resp.get("raw", {}),
        )

    def budget_status(self) -> dict[str, float]:
        """返回今日预算消耗状况。"""
        today = time.strftime("%Y-%m-%d")
        if self._daily_date != today:
            return {"date": today, "spent_yuan": 0.0, "limit_yuan": self._budget, "ok": True}
        return {
            "date": today,
            "spent_yuan": self._daily_spent,
            "limit_yuan": self._budget,
            "ok": self._daily_spent < self._budget,
        }

    # -------------------------------------------------------------------------
    # 内部路由
    # -------------------------------------------------------------------------

    def _check_budget(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self._daily_date != today:
            self._daily_date = today
            self._daily_spent = 0.0
        if self._daily_spent >= self._budget:
            raise BudgetExceededError(
                f"[AIDispatcher] 日预算上限 ¥{self._budget} 已触发（已用 ¥{self._daily_spent:.2f}）；"
                "remote 调用被拒绝，请联系架构师调整 AI_DISPATCHER_BUDGET_YUAN_DAILY"
            )

    def _record_spend(self, cost: float) -> None:
        self._daily_spent += cost

    def _call_deepseek(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        model_override: str | None = None,
        *,
        scene: Scene = "dry_run",
    ) -> dict:
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key:
            if scene == "radar_distill":
                raise RuntimeError("未配置 DEEPSEEK_API_KEY；T1 DeepSeek 压缩不可用")
            return self._call_mock(messages)

        base = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        model = (model_override or "").strip()
        if model.startswith("deepseek:"):
            model = model.split(":", 1)[1]
        if not model:
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"

        try:
            import httpx  # noqa: PLC0415

            proxy = (os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip()
            client_kw: dict[str, Any] = {"timeout": httpx.Timeout(120.0, connect=30.0)}
            if proxy:
                client_kw["proxy"] = proxy
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            with httpx.Client(**client_kw) as client:
                r = client.post(
                    f"{base}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            usage = data.get("usage") or {}
            return {
                "text": text,
                "model": f"deepseek:{model}",
                "tokens_in": int(usage.get("prompt_tokens") or 0),
                "tokens_out": int(usage.get("completion_tokens") or 0),
                "raw": data,
            }
        except Exception as exc:
            logger.warning("[AIDispatcher] DeepSeek 调用失败: %s", exc)
            if scene == "radar_distill":
                raise RuntimeError(f"DeepSeek API 不可达：{exc}") from exc
            return self._call_mock(messages)

    def _call_remote(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        model_override: str | None = None,
        *,
        scene: Scene = "dry_run",
    ) -> dict:
        if not self._anthropic_client:
            logger.warning("[AIDispatcher] remote 路由降级 → mock（未配置 ANTHROPIC_API_KEY）")
            if scene == "radar_assess":
                raise RuntimeError(
                    "未配置 ANTHROPIC_API_KEY；模式 C 深度研报不可用（no-mock）"
                )
            return self._call_mock(messages)

        system = ""
        user_msgs: list[dict[str, str]] = []
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            else:
                user_msgs.append(m)

        model = (model_override or "").strip() or self._anthropic_model
        try:
            resp = self._anthropic_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                **({"system": system} if system else {}),
                messages=user_msgs,
            )
            text = resp.content[0].text if resp.content else ""
            return {
                "text": text,
                "model": model,
                "tokens_in": resp.usage.input_tokens,
                "tokens_out": resp.usage.output_tokens,
                "raw": resp.model_dump() if hasattr(resp, "model_dump") else {},
            }
        except Exception as exc:
            logger.warning("[AIDispatcher] remote 调用失败: %s", exc)
            if scene == "radar_assess":
                raise RuntimeError(
                    f"Opus API 不可达：{exc}；请配置 HTTPS_PROXY 或本机预拉后 sync 缓存"
                ) from exc
            logger.warning("[AIDispatcher] remote 调用失败 → mock 降级")
            return self._call_mock(messages)

    def _call_local(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """调用本地 vLLM OpenAI 兼容 API（Qwen-14B + LoRA @ :8091）。"""
        try:
            import httpx  # noqa: PLC0415

            payload = {
                "model": "qwen-14b",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            r = httpx.post(
                f"{self._vllm_base}/chat/completions",
                json=payload,
                timeout=30.0,
            )
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {
                "text": text,
                "model": data.get("model", "qwen-14b"),
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
                "raw": data,
            }
        except Exception as exc:
            logger.warning("[AIDispatcher] local vLLM 不可用 → mock 降级: %s", exc)
            return self._call_mock(messages)

    @staticmethod
    def _call_mock(messages: list[dict[str, str]]) -> dict:
        user_text = " ".join(
            m["content"] for m in messages if m.get("role") != "system"
        )
        mock_body = {
            "decision": "mock",
            "confidence": 0.0,
            "_dispatcher_mock": True,
            "_input_hash": hash(user_text) & 0xFFFFFFFF,
        }
        return {
            "text": json.dumps(mock_body, ensure_ascii=False),
            "model": "mock",
            "tokens_in": 0,
            "tokens_out": 0,
            "raw": mock_body,
        }
