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
[Ref: 26_行情雷达与AI模型工作流 · 仅 Opus 走新加坡出口代理]
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


def anthropic_https_proxy_url() -> str:
    """仅 Anthropic/Opus 使用的出口代理（勿设进程级 HTTPS_PROXY）。"""
    return (
        os.getenv("ANTHROPIC_HTTPS_PROXY")
        or os.getenv("anthropic_https_proxy")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or ""
    ).strip()


def _parse_proxy_host_port(proxy_url: str) -> tuple[str, int] | None:
    """从 ANTHROPIC_HTTPS_PROXY URL 解析 host/port（用于 TCP 探活）。"""
    raw = (proxy_url or "").strip()
    if not raw:
        return None
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            tail = raw.split("@")[-1].replace("http://", "").replace("https://", "")
            host, _, port_s = tail.partition(":")
            port = int(port_s.split("/")[0]) if port_s else 3128
        return host, int(port)
    except (TypeError, ValueError):
        return None


def probe_anthropic_proxy_tcp(*, timeout_sec: float = 10.0) -> tuple[bool, str]:
    """TCP 探活新加坡出口代理；失败时返回可执行修复提示。"""
    proxy = anthropic_https_proxy_url()
    if not proxy:
        return True, "direct"
    parsed = _parse_proxy_host_port(proxy)
    if not parsed:
        return False, f"ANTHROPIC_HTTPS_PROXY 格式无效：{proxy[:80]}"
    host, port = parsed
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(max(1.0, float(timeout_sec)))
    try:
        sock.connect((host, port))
        return True, f"{host}:{port}"
    except OSError as exc:
        return False, (
            f"Anthropic 出口代理不可达（{host}:{port} · {exc}）。"
            "常见原因：新加坡 ECS/EIP 已重建但 Copilot Secret 仍指向旧 IP。"
            "请在 diting-infra 执行：make verify-sg-anthropic-proxy && make sync-anthropic-proxy-to-copilot"
        )
    finally:
        try:
            sock.close()
        except OSError:
            pass


def anthropic_omit_temperature(model: str) -> bool:
    """Opus 4.5+ 部分型号已弃用 temperature 参数。"""
    m = (model or "").lower()
    prefixes = (
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-4-5",
    )
    return any(m.startswith(p) for p in prefixes)


def anthropic_read_timeout_sec(*, scene: Scene, max_tokens: int) -> float:
    """T2 大 payload 读超时放宽（16k 输出 + 流式仍须留足余量）。"""
    if scene == "radar_assess" and max_tokens >= 16_384:
        return 900.0
    if scene == "radar_assess" and max_tokens >= 8192:
        return 600.0
    if scene == "radar_assess" and max_tokens >= 4096:
        return 300.0
    return 120.0


def deepseek_read_timeout_sec(*, scene: Scene, max_tokens: int) -> float:
    """DeepSeek 读超时：按 max_tokens ÷ 50 tok/s 估算，加 60s 缓冲。"""
    estimate = max(max_tokens / 50, 60)
    return estimate + 60.0


def anthropic_use_streaming(*, scene: Scene, max_tokens: int) -> bool:
    """长输出走流式；经 HTTP 代理时默认关闭（3proxy 对 SSE chunked 易 incomplete chunked read）。"""
    if anthropic_https_proxy_url():
        return os.getenv("ANTHROPIC_FORCE_STREAMING", "").lower() in (
            "1",
            "true",
            "yes",
        )
    return scene == "radar_assess" and max_tokens >= 4096


def is_transient_anthropic_error(exc: BaseException) -> bool:
    """经 HTTPS 代理的长 Opus 请求常见瞬态断连（可重试或降级 non-stream）。"""
    msg = str(exc).lower()
    needles = (
        "timed out",
        "timeout",
        "interrupted",
        "connection reset",
        "connection error",
        "temporarily unavailable",
        "peer closed",
        "incomplete chunked",
        "chunked read",
        "server disconnected",
        "without sending a response",
        "remote protocol error",
        "broken pipe",
        "connection aborted",
        "read error",
    )
    return any(n in msg for n in needles)


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
    "genesis_ecosystem",
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
    "genesis_ecosystem": "deepseek",
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
        self._anthropic_http_client: Any = None
        if self._anthropic_key:
            self._init_anthropic_client()

    @classmethod
    def default(cls) -> "AIDispatcher":
        """全局单例，自动从环境变量初始化。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _default_read_timeout_sec(self) -> float:
        return float(
            os.getenv(
                "ANTHROPIC_READ_TIMEOUT_SEC",
                str(
                    anthropic_read_timeout_sec(
                        scene="radar_assess", max_tokens=32_768
                    )
                ),
            )
        )

    def _init_anthropic_client(self) -> None:
        if not self._anthropic_key:
            return
        try:
            import anthropic  # noqa: PLC0415

            read_timeout = self._default_read_timeout_sec()
            client_kw: dict[str, Any] = {
                "api_key": self._anthropic_key,
                "base_url": self._anthropic_base,
                "timeout": read_timeout,
            }
            proxy = anthropic_https_proxy_url()
            if proxy:
                import httpx  # noqa: PLC0415

                self._anthropic_http_client = httpx.Client(
                    proxy=proxy,
                    timeout=httpx.Timeout(read_timeout, connect=30.0),
                    http2=False,
                )
                client_kw["http_client"] = self._anthropic_http_client
                logger.info(
                    "[AIDispatcher] Anthropic 客户端使用 ANTHROPIC_HTTPS_PROXY · read_timeout=%ss · http2=off",
                    int(read_timeout),
                )
            self._anthropic_client = anthropic.Anthropic(**client_kw)
        except ImportError:
            logger.warning("anthropic SDK 未安装；remote 路由将不可用（pip install anthropic）")

    def _reset_anthropic_transport(self) -> None:
        """瞬态断连后丢弃 httpx 连接池，下次调用重建。"""
        self._anthropic_client = None
        if self._anthropic_http_client is not None:
            try:
                self._anthropic_http_client.close()
            except Exception:  # noqa: BLE001
                pass
            self._anthropic_http_client = None
        self._init_anthropic_client()

    def _remote_stream_once(
        self,
        create_kw: dict[str, Any],
        *,
        read_timeout: float,
        model: str,
    ) -> dict[str, Any]:
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client unavailable")
        text_parts: list[str] = []
        with self._anthropic_client.messages.stream(
            **create_kw, timeout=read_timeout
        ) as stream:
            for chunk in stream.text_stream:
                text_parts.append(chunk)
            final = stream.get_final_message()
        text = "".join(text_parts)
        raw = final.model_dump() if hasattr(final, "model_dump") else {}
        if raw and "stop_reason" not in raw and hasattr(final, "stop_reason"):
            raw["stop_reason"] = final.stop_reason
        raw["_streaming"] = True
        usage = final.usage
        return {
            "text": text,
            "model": model,
            "tokens_in": usage.input_tokens,
            "tokens_out": usage.output_tokens,
            "raw": raw,
        }

    def _make_ephemeral_anthropic_client(self, read_timeout: float) -> tuple[Any, Any | None]:
        """T2 长连接：每次独立 httpx 连接，避免单例连接池复用半开 CONNECT 隧道。"""
        import anthropic  # noqa: PLC0415

        client_kw: dict[str, Any] = {
            "api_key": self._anthropic_key,
            "base_url": self._anthropic_base,
            "timeout": read_timeout,
        }
        http_client: Any = None
        proxy = anthropic_https_proxy_url()
        if proxy:
            import httpx  # noqa: PLC0415

            http_client = httpx.Client(
                proxy=proxy,
                timeout=httpx.Timeout(read_timeout, connect=30.0),
                http2=False,
            )
            client_kw["http_client"] = http_client
        return anthropic.Anthropic(**client_kw), http_client

    def _remote_create_once(
        self,
        create_kw: dict[str, Any],
        *,
        read_timeout: float,
        model: str,
        client: Any | None = None,
    ) -> dict[str, Any]:
        anthropic_client = client or self._anthropic_client
        if not anthropic_client:
            raise RuntimeError("Anthropic client unavailable")
        resp = anthropic_client.messages.create(
            **create_kw, timeout=read_timeout
        )
        text = resp.content[0].text if resp.content else ""
        raw = resp.model_dump() if hasattr(resp, "model_dump") else {}
        if raw and "stop_reason" not in raw and hasattr(resp, "stop_reason"):
            raw["stop_reason"] = resp.stop_reason
        raw["_streaming"] = False
        return {
            "text": text,
            "model": model,
            "tokens_in": resp.usage.input_tokens,
            "tokens_out": resp.usage.output_tokens,
            "raw": raw,
        }

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

    @staticmethod
    def _format_deepseek_error(exc: BaseException) -> str:
        """将 DeepSeek HTTP/API 异常转为用户可读中文（勿一律写成「未配置 key」）。"""
        msg = str(exc)
        low = msg.lower()
        if "402" in msg or "insufficient balance" in low or "payment required" in low:
            return "DeepSeek 账户余额不足（402 Payment Required），请登录 platform.deepseek.com 充值后重试"
        if "401" in msg or "invalid api key" in low or "authentication" in low:
            return "DeepSeek API Key 无效或已过期（401），请检查 DEEPSEEK_API_KEY"
        if "429" in msg or "rate limit" in low:
            return "DeepSeek 请求过于频繁（429），请稍后重试"
        return f"DeepSeek API 调用失败：{msg[:240]}"

    def _deepseek_no_mock_scenes(self) -> frozenset[Scene]:
        return frozenset({"radar_distill", "radar_assess", "radar_chat"})

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
            if scene in self._deepseek_no_mock_scenes():
                raise RuntimeError("未配置 DEEPSEEK_API_KEY；DeepSeek 路由不可用")
            return self._call_mock(messages)

        base = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        from apps.copilot.modules.radar.deepseek_models import resolve_deepseek_api

        api_model, enable_thinking = resolve_deepseek_api(model_override)
        model = api_model
        if not model:
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"

        try:
            import httpx  # noqa: PLC0415

            read_to = deepseek_read_timeout_sec(scene=scene, max_tokens=max_tokens)
            client_kw: dict[str, Any] = {"timeout": httpx.Timeout(read_to, connect=30.0)}
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if enable_thinking:
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = "high"
            else:
                payload["temperature"] = temperature
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
            msg = choice.get("message") or {}
            text = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning_content") or "").strip()
            if not text and reasoning:
                text = reasoning
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
            if scene in self._deepseek_no_mock_scenes():
                raise RuntimeError(self._format_deepseek_error(exc)) from exc
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
        create_kw: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": user_msgs,
        }
        if system:
            create_kw["system"] = system
        if not anthropic_omit_temperature(model):
            create_kw["temperature"] = temperature
        read_timeout = anthropic_read_timeout_sec(scene=scene, max_tokens=max_tokens)
        use_stream = anthropic_use_streaming(scene=scene, max_tokens=max_tokens)
        use_ephemeral = scene == "radar_assess" and bool(anthropic_https_proxy_url())
        if scene == "radar_assess" and anthropic_https_proxy_url():
            ok, detail = probe_anthropic_proxy_tcp(
                timeout_sec=float(os.getenv("ANTHROPIC_PROXY_CONNECT_PROBE_SEC", "10"))
            )
            if not ok:
                raise RuntimeError(detail)
        try:
            if use_stream and not use_ephemeral:
                return self._remote_stream_once(
                    create_kw, read_timeout=read_timeout, model=model
                )

            def _create_with_client(client: Any | None) -> dict[str, Any]:
                return self._remote_create_once(
                    create_kw,
                    read_timeout=read_timeout,
                    model=model,
                    client=client,
                )

            if use_ephemeral:
                max_attempts = max(
                    1,
                    int(os.getenv("ANTHROPIC_PROXY_MAX_ATTEMPTS", "3")),
                )
                last_exc: Exception | None = None
                for attempt in range(max_attempts):
                    ep_client, ep_http = self._make_ephemeral_anthropic_client(read_timeout)
                    try:
                        out = _create_with_client(ep_client)
                        out.setdefault("raw", {})["_ephemeral_client"] = True
                        out.setdefault("raw", {})["_proxy_attempt"] = attempt + 1
                        return out
                    except Exception as exc:
                        last_exc = exc
                        if (
                            attempt < max_attempts - 1
                            and is_transient_anthropic_error(exc)
                        ):
                            wait = min(30.0, 2.0 * (2**attempt))
                            logger.warning(
                                "[AIDispatcher] T2 经代理 non-stream 瞬态失败 attempt=%s/%s，"
                                "%.0fs 后换新连接重试: %s",
                                attempt + 1,
                                max_attempts,
                                wait,
                                exc,
                            )
                            time.sleep(wait)
                            continue
                        raise
                    finally:
                        if ep_http is not None:
                            try:
                                ep_http.close()
                            except Exception:  # noqa: BLE001
                                pass
                if last_exc:
                    raise last_exc

            return _create_with_client(None)
        except Exception as exc:
            logger.warning("[AIDispatcher] remote 调用失败: %s", exc)
            if scene == "radar_assess":
                raise RuntimeError(
                    f"Opus API 不可达：{exc}；请配置 ANTHROPIC_HTTPS_PROXY 或本机预拉后 sync 缓存"
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
