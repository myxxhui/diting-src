"""雷达 Opus 日常对话（多轮 messages · Redis/内存会话 · 研究 advisory）。

[Ref: step_14 · 25_ §2 · 共享规约 19 AIDispatcher]
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from apps.copilot.modules.radar.schema import estimate_cost_yuan

logger = logging.getLogger(__name__)

CHAT_SYSTEM = (
    "你是 Diting「行情解析与规划工作台」中的 Opus 研究对话助手，面向 A 股个人投资者。\n"
    "职责：解答投资研究、产业逻辑、财报解读、估值框架、风险识别等日常问题；"
    "语气专业、条理清晰，优先中文。\n"
    "红线：① 仅提供研究 advisory，不构成买卖指令；禁止「立即买入/卖出/加仓/清仓」等交易措辞；"
    "② 不编造未给出的数据与公告；不确定时明确说明；"
    "③ 可结合用户附带的标的上下文做分析，无上下文时按通用框架回答。"
)

_MAX_TURNS = 24
_MAX_USER_CHARS = 4000
_REDIS_TTL_SEC = 7 * 24 * 3600
_memory_sessions: dict[str, list[dict[str, str]]] = {}

# 雷达对话可选 Opus 型号（model_id, 展示名）
RADAR_CHAT_MODELS: list[tuple[str, str]] = [
    ("claude-opus-4-5-20251101", "Opus 4.5"),
    ("claude-opus-4-6", "Opus 4.6"),
    ("claude-opus-4-7", "Opus 4.7"),
    ("claude-opus-4-8", "Opus 4.8"),
    ("claude-opus-4-9", "Opus 4.9"),
    ("claude-opus-4-20250514", "Opus 4（20250514）"),
    ("claude-3-opus-20240229", "Opus 3"),
]

DEFAULT_CHAT_MODEL = os.getenv("RADAR_CHAT_DEFAULT_MODEL", "claude-opus-4-6")


def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def _redis_key(session_id: str) -> str:
    return f"radar:chat:{session_id}"


def load_messages(redis_client: Any, session_id: str) -> list[dict[str, str]]:
    sid = (session_id or "").strip()
    if not sid:
        return []
    if redis_client is not None:
        try:
            raw = redis_client.get(_redis_key(sid))
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [m for m in data if m.get("role") in ("user", "assistant")]
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取对话会话失败 sid=%s: %s", sid, exc)
    return list(_memory_sessions.get(sid, []))


def save_messages(
    redis_client: Any,
    session_id: str,
    messages: list[dict[str, str]],
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    trimmed = messages[-_MAX_TURNS * 2 :]
    if redis_client is not None:
        try:
            redis_client.setex(
                _redis_key(sid),
                _REDIS_TTL_SEC,
                json.dumps(trimmed, ensure_ascii=False),
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入对话会话失败 sid=%s: %s", sid, exc)
    _memory_sessions[sid] = trimmed


def clear_session(redis_client: Any, session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    if redis_client is not None:
        try:
            redis_client.delete(_redis_key(sid))
        except Exception:  # noqa: BLE001
            pass
    _memory_sessions.pop(sid, None)


def _build_system_extra(symbol: str | None, context: dict[str, Any] | None) -> str:
    if not symbol and not context:
        return CHAT_SYSTEM
    lines = [CHAT_SYSTEM, "", "【当前附带标的上下文（供参考，可忽略）】"]
    if symbol:
        lines.append(f"标的代码：{symbol}")
    if context:
        name = context.get("name") or symbol
        lines.append(f"名称：{name}")
        overall = (context.get("deep_analysis") or {}).get("overall") or {}
        if overall.get("conclusion"):
            lines.append(f"最近扫描结论：{overall['conclusion']}")
        if overall.get("action_advisory"):
            lines.append(f"研究 advisory：{overall['action_advisory']}")
    return "\n".join(lines)


def resolve_chat_model(model_id: str | None) -> str:
    mid = (model_id or "").strip() or DEFAULT_CHAT_MODEL
    allowed = {m[0] for m in RADAR_CHAT_MODELS}
    if mid in allowed:
        return mid
    return DEFAULT_CHAT_MODEL


async def chat_turn(
    redis_client: Any,
    *,
    session_id: str,
    user_message: str,
    symbol: str | None = None,
    scan_context: dict[str, Any] | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """用户一轮输入 → Opus 回复；返回完整会话与元数据。"""
    import asyncio

    sid = (session_id or "").strip() or new_session_id()
    text = (user_message or "").strip()
    if not text:
        raise ValueError("请输入消息内容")
    if len(text) > _MAX_USER_CHARS:
        raise ValueError(f"消息过长（>{_MAX_USER_CHARS} 字）")

    history = load_messages(redis_client, sid)
    history.append({"role": "user", "content": text})

    api_messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_extra(symbol, scan_context)},
    ]
    api_messages.extend(history)

    def _blocking() -> Any:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        try:
            # 与 radar_assess 同走 remote/Opus；热修镜像未更新 Scene 时用 assess
            scene = "radar_chat"
            try:
                return AIDispatcher.default().call(
                    scene,
                    messages=api_messages,
                    max_tokens=4096,
                    temperature=0.4,
                    model_override=resolve_chat_model(model_id),
                )
            except Exception:
                return AIDispatcher.default().call(
                    "radar_assess",
                    messages=api_messages,
                    max_tokens=4096,
                    temperature=0.4,
                    model_override=resolve_chat_model(model_id),
                )
        except BudgetExceededError as exc:
            raise RuntimeError(f"日预算上限：{exc}") from exc

    try:
        resp = await asyncio.to_thread(_blocking)
    except Exception as exc:  # noqa: BLE001
        history.pop()
        return {
            "session_id": sid,
            "messages": history,
            "error": str(exc)[:300],
            "status": "error",
        }

    if resp.model == "mock" or (resp.raw or {}).get("_dispatcher_mock"):
        history.pop()
        return {
            "session_id": sid,
            "messages": history,
            "error": (
                "Opus 不可达（请配置 ANTHROPIC_API_KEY / HTTPS_PROXY，"
                "或本机预拉后使用扫描缓存）"
            ),
            "status": "error",
            "route": resp.route,
        }

    assistant_text = (resp.text or "").strip() or "（模型未返回正文）"
    cost = estimate_cost_yuan(resp.tokens_in, resp.tokens_out)
    if resp.cost_yuan_est and resp.cost_yuan_est > 0:
        cost = resp.cost_yuan_est
    history.append(
        {
            "role": "assistant",
            "content": assistant_text,
            "meta": {
                "model": resp.model,
                "cost_yuan": cost,
                "tokens_in": resp.tokens_in,
                "tokens_out": resp.tokens_out,
                "latency_ms": resp.latency_ms,
            },
        }
    )
    save_messages(redis_client, sid, history)

    return {
        "session_id": sid,
        "messages": history,
        "status": "ok",
        "model": resp.model,
        "route": resp.route,
        "tokens_in": resp.tokens_in,
        "tokens_out": resp.tokens_out,
        "cost_yuan": cost,
        "latency_ms": resp.latency_ms,
    }
