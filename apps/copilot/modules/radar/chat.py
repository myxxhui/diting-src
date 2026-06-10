"""雷达 Opus 日常对话（多轮 messages · PG 底库 + Redis 热缓存 · 研究 advisory）。

[Ref: step_14 · 25_ §2 · 共享规约 19 AIDispatcher]
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import RadarChatSession
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

# Opus 型号（model_id, 展示名）· 仅保留生产 API 实测可用的 slug
OPUS_CHAT_MODELS: list[tuple[str, str]] = [
    ("claude-opus-4-6", "Opus 4.6（推荐）"),
    ("claude-opus-4-5-20251101", "Opus 4.5"),
    ("claude-opus-4-7", "Opus 4.7"),
    ("claude-opus-4-8", "Opus 4.8"),
]

from apps.copilot.modules.radar.deepseek_models import (
    DEEPSEEK_CHAT_MODELS,
    DEEPSEEK_MODEL_ALIASES,
)

RADAR_CHAT_MODELS: list[tuple[str, str]] = OPUS_CHAT_MODELS + DEEPSEEK_CHAT_MODELS

OPUS_MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4-5": "claude-opus-4-5-20251101",
    "claude-opus-4-9": "claude-opus-4-6",
    "claude-opus-4-20250514": "claude-opus-4-6",
    "claude-3-opus-20240229": "claude-opus-4-6",
}

DEFAULT_CHAT_MODEL = os.getenv("RADAR_CHAT_DEFAULT_MODEL", "claude-opus-4-6")


def resolve_chat_model(model_id: str | None) -> str:
    """T2 / Opus 页对话：校验并归一化 Opus 或 DeepSeek model slug。"""
    mid = (model_id or "").strip() or DEFAULT_CHAT_MODEL
    mid = DEEPSEEK_MODEL_ALIASES.get(mid, mid)
    if not mid.startswith("deepseek:"):
        mid = OPUS_MODEL_ALIASES.get(mid, mid)
    allowed = {m[0] for m in RADAR_CHAT_MODELS}
    if mid in allowed:
        return mid
    return DEFAULT_CHAT_MODEL


def chat_model_route(resolved_model: str) -> str:
    """返回 AIDispatcher force_route：remote（Anthropic）或 deepseek。"""
    return "deepseek" if (resolved_model or "").startswith("deepseek:") else "remote"


def resolve_opus_model(model_id: str | None) -> str:
    """仅 Opus slug 归一化（雷达模式 C 等 Anthropic 专用路径）。"""
    mid = (model_id or "").strip() or DEFAULT_CHAT_MODEL
    mid = OPUS_MODEL_ALIASES.get(mid, mid)
    allowed = {m[0] for m in OPUS_CHAT_MODELS}
    if mid in allowed:
        return mid
    return DEFAULT_CHAT_MODEL


def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def _redis_key(session_id: str) -> str:
    return f"radar:chat:{session_id}"


def _trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return messages[-_MAX_TURNS * 2 :]


def title_from_messages(messages: list[dict[str, Any]], *, default: str = "新对话") -> str:
    for m in messages:
        if m.get("role") == "user":
            text = (m.get("content") or "").strip()
            if text:
                return text[:48]
    return default


def _load_messages_from_redis(redis_client: Any, session_id: str) -> list[dict[str, Any]] | None:
    if redis_client is None:
        return None
    sid = (session_id or "").strip()
    if not sid:
        return None
    try:
        raw = redis_client.get(_redis_key(sid))
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, list):
            return [m for m in data if m.get("role") in ("user", "assistant")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取雷达对话 Redis 失败 sid=%s: %s", sid, exc)
    return None


def _save_messages_to_redis(
    redis_client: Any, session_id: str, messages: list[dict[str, Any]]
) -> None:
    if redis_client is None:
        return
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        redis_client.setex(
            _redis_key(sid),
            _REDIS_TTL_SEC,
            json.dumps(_trim_messages(messages), ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入雷达对话 Redis 失败 sid=%s: %s", sid, exc)


def load_messages(redis_client: Any, session_id: str) -> list[dict[str, str]]:
    """同步加载（内存 → Redis）；路由层应优先用 load_messages_async。"""
    sid = (session_id or "").strip()
    if not sid:
        return []
    cached = _memory_sessions.get(sid)
    if cached:
        return list(cached)
    redis_msgs = _load_messages_from_redis(redis_client, sid)
    if redis_msgs is not None:
        _memory_sessions[sid] = redis_msgs
        return list(redis_msgs)
    return list(_memory_sessions.get(sid, []))


async def load_messages_async(
    session_id: str,
    *,
    redis_client: Any = None,
    db_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """加载雷达对话：内存 → Redis → PG。"""
    sid = (session_id or "").strip()
    if not sid:
        return []

    cached = _memory_sessions.get(sid)
    if cached:
        return list(cached)

    redis_msgs = _load_messages_from_redis(redis_client, sid)
    if redis_msgs is not None:
        _memory_sessions[sid] = redis_msgs
        return list(redis_msgs)

    if db_session is not None:
        row = await db_session.scalar(
            select(RadarChatSession).where(RadarChatSession.session_id == sid)
        )
        if row and row.messages_json:
            msgs = _trim_messages(list(row.messages_json))
            _memory_sessions[sid] = msgs
            _save_messages_to_redis(redis_client, sid, msgs)
            return list(msgs)

    return []


async def persist_radar_session(
    db_session: AsyncSession,
    session_id: str,
    messages: list[dict[str, Any]],
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    trimmed = _trim_messages(messages)
    row = await db_session.scalar(
        select(RadarChatSession).where(RadarChatSession.session_id == sid)
    )
    if row is None:
        row = RadarChatSession(session_id=sid, messages_json=trimmed)
        db_session.add(row)
    else:
        row.messages_json = trimmed
    await db_session.flush()


async def save_messages_async(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    redis_client: Any = None,
    db_session: AsyncSession | None = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    trimmed = _trim_messages(messages)
    _memory_sessions[sid] = trimmed
    _save_messages_to_redis(redis_client, sid, trimmed)
    if db_session is not None:
        await persist_radar_session(db_session, sid, trimmed)


def save_messages(
    redis_client: Any,
    session_id: str,
    messages: list[dict[str, str]],
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    trimmed = _trim_messages(messages)
    _memory_sessions[sid] = trimmed
    _save_messages_to_redis(redis_client, sid, trimmed)


async def clear_session_async(
    session_id: str,
    *,
    redis_client: Any = None,
    db_session: AsyncSession | None = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    _memory_sessions.pop(sid, None)
    if redis_client is not None:
        try:
            redis_client.delete(_redis_key(sid))
        except Exception:  # noqa: BLE001
            pass
    if db_session is not None:
        row = await db_session.scalar(
            select(RadarChatSession).where(RadarChatSession.session_id == sid)
        )
        if row is not None:
            await db_session.delete(row)
            await db_session.flush()


def clear_session(redis_client: Any, session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    _memory_sessions.pop(sid, None)
    if redis_client is not None:
        try:
            redis_client.delete(_redis_key(sid))
        except Exception:  # noqa: BLE001
            pass


async def list_radar_chat_sessions(
    db_session: AsyncSession,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    rows = (
        await db_session.scalars(
            select(RadarChatSession)
            .order_by(RadarChatSession.updated_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        msgs = row.messages_json or []
        if not msgs:
            continue
        ts = int(row.updated_at.timestamp() * 1000) if row.updated_at else 0
        out.append(
            {
                "id": row.session_id,
                "title": title_from_messages(msgs, default="新对话"),
                "updatedAt": ts,
            }
        )
    return out


async def warm_radar_chat_sessions_from_pg(
    db_session: AsyncSession,
    redis_client: Any,
    *,
    limit: int = 50,
) -> dict[str, int]:
    if not redis_client:
        return {"sessions": 0, "warmed": 0, "skipped": "no_redis"}

    rows = (
        await db_session.scalars(
            select(RadarChatSession)
            .order_by(RadarChatSession.updated_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    warmed = 0
    for row in rows:
        msgs = row.messages_json or []
        if msgs:
            _save_messages_to_redis(redis_client, row.session_id, msgs)
            _memory_sessions[row.session_id] = _trim_messages(list(msgs))
            warmed += 1
    logger.info("雷达对话 Redis 预热 sessions=%d warmed=%d", len(rows), warmed)
    return {"sessions": len(rows), "warmed": warmed}


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


async def chat_turn(
    redis_client: Any,
    *,
    session_id: str,
    user_message: str,
    symbol: str | None = None,
    scan_context: dict[str, Any] | None = None,
    model_id: str | None = None,
    db_session: AsyncSession | None = None,
) -> dict[str, Any]:
    """用户一轮输入 → Opus 回复；返回完整会话与元数据。"""
    import asyncio

    sid = (session_id or "").strip() or new_session_id()
    text = (user_message or "").strip()
    if not text:
        raise ValueError("请输入消息内容")
    if len(text) > _MAX_USER_CHARS:
        raise ValueError(f"消息过长（>{_MAX_USER_CHARS} 字）")

    history = await load_messages_async(
        sid, redis_client=redis_client, db_session=db_session
    )
    history.append({"role": "user", "content": text})

    api_messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_extra(symbol, scan_context)},
    ]
    api_messages.extend(history)

    resolved = resolve_chat_model(model_id)
    route = chat_model_route(resolved)

    def _blocking() -> Any:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        try:
            scene = "radar_chat"
            try:
                return AIDispatcher.default().call(
                    scene,
                    messages=api_messages,
                    max_tokens=4096,
                    temperature=0.4,
                    force_route=route,
                    model_override=resolved,
                )
            except Exception:
                return AIDispatcher.default().call(
                    "radar_assess",
                    messages=api_messages,
                    max_tokens=4096,
                    temperature=0.4,
                    force_route=route,
                    model_override=resolved,
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
        unreachable = (
            "DeepSeek 调用失败（请检查 DEEPSEEK_API_KEY 有效性或账户余额）"
            if route == "deepseek"
            else "Opus 不可达（请配置 ANTHROPIC_API_KEY / HTTPS_PROXY）"
        )
        return {
            "session_id": sid,
            "messages": history,
            "error": unreachable,
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
    await save_messages_async(
        sid, history, redis_client=redis_client, db_session=db_session
    )
    if db_session is not None:
        await db_session.commit()

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
