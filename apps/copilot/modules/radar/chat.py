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
    """加载雷达对话：内存 → Redis → PG（三级回退，PG 故障也尝试 Redis 直读）。"""
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
        try:
            row = await db_session.scalar(
                select(RadarChatSession).where(RadarChatSession.session_id == sid)
            )
            if row and row.messages_json:
                msgs = _trim_messages(list(row.messages_json))
                _memory_sessions[sid] = msgs
                _save_messages_to_redis(redis_client, sid, msgs)
                return list(msgs)
        except Exception as exc:
            logger.warning("从 PG 加载雷达对话 sid=%s 失败: %s", sid, exc)
            # PG 失败时再尝试一次 Redis（防止连接池耗尽导致误判 redis 无数据）
            if redis_client is not None:
                retry = _load_messages_from_redis(redis_client, sid)
                if retry is not None:
                    _memory_sessions[sid] = retry
                    return list(retry)

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
    try:
        row = await db_session.scalar(
            select(RadarChatSession).where(RadarChatSession.session_id == sid)
        )
        if row is None:
            row = RadarChatSession(session_id=sid, messages_json=trimmed)
            db_session.add(row)
        else:
            row.messages_json = trimmed
        await db_session.flush()
    except Exception as exc:
        logger.warning("PG 持久化雷达对话 sid=%s 失败: %s", sid, exc)


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
    if not messages:
        # 禁止写入空消息列表（防内容丢失）
        logger.warning("save_messages_async sid=%s 拒绝写入空消息列表", sid)
        return
    trimmed = _trim_messages(messages)
    _memory_sessions[sid] = trimmed
    _save_messages_to_redis(redis_client, sid, trimmed)
    if db_session is not None:
        try:
            await persist_radar_session(db_session, sid, trimmed)
        except Exception as exc:
            logger.warning("PG 持久化雷达对话 sid=%s 异常: %s（已落 Redis，下次加载会重试 PG）", sid, exc)


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
        ts = int(row.updated_at.timestamp() * 1000) if row.updated_at else 0
        if not msgs:
            out.append(
                {
                    "id": row.session_id,
                    "title": "(空对话)",
                    "updatedAt": ts,
                }
            )
        else:
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


def _compact_envelope_for_chat(envelope: dict[str, Any]) -> dict[str, Any]:
    """自由研究对话注入的 T1/JL 数据包（与 T2 envelope 同源，裁剪体积）。

    裁剪规则：
    - 指标中去除 t1_json / raw_metrics（内部审计中间件，模型无需）
    - checklist 去除 reply 模板（指令已在 user 消息中）
    """
    up = envelope.get("user_payload") or {}
    t1 = up.get("t1") or {}

    # ── 精简 checklist：只保留 topic_id/key + question，去掉 reply 模板 ──
    checklist_raw = up.get("checklist")
    checklist_lean: dict[str, Any] | None = None
    if isinstance(checklist_raw, dict):
        checklist_lean = {}
        for sym_k, sym_v in checklist_raw.items():
            lean_sym: dict[str, list] = {"name": sym_v.get("name", sym_k)}
            for layer in ("jl1", "jl2", "jl3"):
                items = sym_v.get(layer) or []
                lean_items: list[dict] = []
                for item in items:
                    lean_item = {"q": item.get("question") or item.get("key", "")}
                    lean_item["id"] = item.get("topic_id") or item.get("key", "")
                    lean_items.append(lean_item)
                if lean_items:
                    lean_sym[layer] = lean_items
            checklist_lean[sym_k] = lean_sym

    # ── 精简 t1.portfolio_signals：每个指标只保留业务字段 ──
    portfolio_signals = t1.get("portfolio_signals") or {}
    portfolio_lean: dict[str, Any] = {}
    for code, sig in portfolio_signals.items():
        lean_sig: dict[str, Any] = {}
        pos = sig.get("position_context")
        if pos:
            lean_sig["position"] = pos
        indicators = sig.get("indicators") or {}
        lean_indicators: dict[str, dict] = {}
        for probe_key, val in indicators.items():
            if not isinstance(val, dict):
                continue
            lean_val: dict[str, Any] = {}
            for keep_key in (
                "indicator_name",
                "value",
                "value_detail",
                "fact_statement",
                "calculation_logic",
                "source",
            ):
                if val.get(keep_key) is not None and val.get(keep_key) != "":
                    lean_val[keep_key] = val[keep_key]
            if lean_val:
                lean_indicators[probe_key] = lean_val
        lean_sig["stock_name"] = sig.get("stock_name", code)
        lean_sig["indicators"] = lean_indicators
        if sig.get("degraded_probes"):
            lean_sig["degraded_probes"] = sig["degraded_probes"]
        portfolio_lean[code] = lean_sig

    return {
        "checklist": checklist_lean,
        "jl4_catalog": up.get("jl4_catalog"),
        "coverage": envelope.get("coverage"),
        "t1": {
            "batch_meta": t1.get("batch_meta"),
            "portfolio_signals": portfolio_lean,
        },
        "profit": up.get("profit"),
    }


async def build_symbol_research_context(
    db_session: AsyncSession,
    symbol: str,
    *,
    include_t1_jl4: bool = True,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    """为自由研究模式组装 JL1–4 数据包（与持仓 T2 envelope 同源）。"""
    from apps.copilot.modules.executing.t1_assembler import assemble_batch_portfolio
    from apps.copilot.modules.executing.t1_build import _symbol_exchange
    from apps.copilot.modules.executing.t2_analyst import strip_jl4_from_t1
    from apps.copilot.modules.executing.t2_preexec_envelope import build_t2_preexec_envelope

    sym = symbol.zfill(6)[-6:]
    code = _symbol_exchange(sym)
    try:
        t1 = await assemble_batch_portfolio(db_session, [sym], redis_client=redis_client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("自由研究 T1 组装失败 sym=%s: %s", sym, exc)
        return None
    signals = t1.get("portfolio_signals") or {}
    if code not in signals:
        logger.warning(
            "自由研究 T1 无 portfolio_signals sym=%s code=%s keys=%s",
            sym,
            code,
            list(signals.keys())[:8],
        )
        return None
    if not include_t1_jl4:
        t1 = strip_jl4_from_t1(t1)
    envelope = build_t2_preexec_envelope(t1)
    sig = signals.get(code) or {}
    return {
        "symbol": sym,
        "signal_key": code,
        "name": sig.get("stock_name") or sym,
        "envelope": envelope,
        "compact": _compact_envelope_for_chat(envelope),
        "jl4_indicator_count": len((sig.get("indicators") or {})),
    }


def _build_system_extra(
    symbol: str | None,
    context: dict[str, Any] | None,
    *,
    research_context: dict[str, Any] | None = None,
) -> str:
    if not symbol and not context and not research_context:
        return CHAT_SYSTEM
    lines = [CHAT_SYSTEM, "", "【当前附带标的上下文（供参考，可忽略）】"]
    if symbol:
        lines.append(f"标的代码：{symbol}")
    if research_context:
        name = research_context.get("name") or symbol
        lines.append(f"名称：{name}")
        jl4_n = research_context.get("jl4_indicator_count")
        if jl4_n is not None:
            lines.append(f"JL4 T1 指标数：{jl4_n}")
        compact = research_context.get("compact")
        if compact:
            lines.append(
                "【JL1–JL4 本地数据包（只读 · JL4 禁止编造未出现数值）】\n"
                + json.dumps(compact, ensure_ascii=False)
            )
    elif context:
        name = context.get("name") or symbol
        lines.append(f"名称：{name}")
        overall = (context.get("deep_analysis") or {}).get("overall") or {}
        if overall.get("conclusion"):
            lines.append(f"最近扫描结论：{overall['conclusion']}")
        if overall.get("action_advisory"):
            lines.append(f"研究 advisory：{overall['action_advisory']}")
    return "\n".join(lines)


def summarize_context_meta(
    *,
    symbol: str | None,
    research_context: dict[str, Any] | None,
    scan_context: dict[str, Any] | None,
    user_text: str,
    system_prompt: str,
    is_subsequent_turn: bool = False,
) -> dict[str, Any]:
    """本轮 API 实际上下文携带摘要（供 UI/日志核对）。"""
    jl13_marker = "【JL1–JL3 公开市场数据补充要求】"
    meta: dict[str, Any] = {
        "symbol": symbol,
        "context_mode": "none",
        "turn": 1 if not is_subsequent_turn else 2,
        "jl13_appended": jl13_marker in (user_text or ""),
        "system_prompt_chars": len(system_prompt or ""),
        "has_jl_envelope_in_system": "JL1–JL4 本地数据包" in (system_prompt or ""),
    }
    if not symbol:
        return meta
    if is_subsequent_turn:
        meta.update(
            {
                "context_mode": "cached_context",
                "note": "JL 数据已在首轮注入，本轮仅沿用历史对话上下文 · 省 token",
            }
        )
        return meta
    if research_context:
        compact = research_context.get("compact") or {}
        checklist = compact.get("checklist") or {}
        meta.update(
            {
                "context_mode": "t1_envelope",
                "signal_key": research_context.get("signal_key"),
                "name": research_context.get("name"),
                "jl4_indicator_count": research_context.get("jl4_indicator_count", 0),
                "checklist_layers": list(checklist.keys())[:12]
                if isinstance(checklist, dict)
                else [],
            }
        )
        return meta
    if scan_context:
        meta.update(
            {
                "context_mode": "radar_scan_fallback",
                "name": scan_context.get("name"),
                "note": "T1 envelope 未命中，仅附带 radar_candidates 扫描结论",
            }
        )
        return meta
    meta.update(
        {
            "context_mode": "symbol_only",
            "note": "未找到 T1 数据包或扫描结论，仅传递标的代码",
        }
    )
    return meta


async def _ensure_research_context(
    db_session: AsyncSession | None,
    symbol: str | None,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    """仅在首轮调用：组装 T1 envelope 全量 JL 数据（有 DB 时走真实装配，无 DB 时返回 None）。"""
    if db_session is None or not symbol:
        return None
    return await build_symbol_research_context(
        db_session, symbol, include_t1_jl4=True, redis_client=redis_client
    )


async def _load_scan_context(
    db_session: AsyncSession, symbol: str
) -> dict[str, Any] | None:
    """T1 未命中时的降级路径：查 radar_candidates 扫描结论。"""
    from sqlalchemy import select
    from apps.copilot.db.models import RadarCandidate

    sym = symbol.zfill(6)[-6:]
    row = await db_session.scalar(
        select(RadarCandidate)
        .where(RadarCandidate.symbol == sym)
        .order_by(RadarCandidate.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    raw = row.raw_json or {}
    return {
        "name": row.name,
        "symbol": row.symbol,
        "deep_analysis": raw.get("deep_analysis") or {},
    }


def _build_system_for_turn(
    *,
    symbol: str | None,
    research_context: dict[str, Any] | None,
    scan_context: dict[str, Any] | None,
    has_prior_assistant: bool,
    force_data: bool = False,
) -> str:
    """构建本轮 system prompt。

    - 首轮（has_prior_assistant=False）+ 有 research_context：注入全量 JL/JL4 数据包
    - 首轮 + 仅 scan_context：注入扫描结论
    - 后续轮 + force_data=True：强制重新注入全量（勾选开关），并附带上下文切换指令
    - 后续轮（has_prior_assistant=True）：轻量版，仅提示已注入上下文
    """
    if research_context and (not has_prior_assistant or force_data):
        base = _build_system_extra(symbol, None, research_context=research_context)
        if has_prior_assistant and force_data:
            name = research_context.get("name") or symbol or ""
            base += (
                f"\n\n【⚠ 上下文切换指令 · 高优先级】"
                f"\n用户刚刚切换了分析标的到 {symbol}（{name}）。"
                f"以下对话历史中的先前回复涉及的是另一个标的，请完全忽略它们。"
                f"你只应基于上面 {symbol} 的数据包进行分析和回答。"
                f"请不要在回复中提及切换标的或历史对话。"
            )
        return base

    if not has_prior_assistant and scan_context:
        return _build_system_extra(symbol, scan_context)

    if has_prior_assistant and symbol:
        return (
            CHAT_SYSTEM
            + f"\n\n【会话级上下文】标的 {symbol} 的 JL1-4/"
            + "T1/基础数据已在本会话首轮注入。后续轮次请参考历史对话中的分析结果，"
            + "无需重复调用外部数据或重新验证已覆盖的指标。"
        )

    return CHAT_SYSTEM


async def chat_turn(
    redis_client: Any,
    *,
    session_id: str,
    user_message: str,
    symbol: str | None = None,
    jl13_data_prompt: str = "",
    model_id: str | None = None,
    db_session: AsyncSession | None = None,
    force_refresh: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """用户一轮输入 → Opus 回复。首轮自动携带 JL/JL4 全量数据；后续轮仅轻量 system。

    force_refresh 数据开关（任意轮次可强制重取）:
      {"base": True, "jl13": True, "jl4": True, "9d": True}
    """
    import asyncio

    from apps.copilot.modules.executing.t2_analyst import (
        DEFAULT_JL13_DATA_TEMPLATE,
        compose_user_question,
    )

    sid = (session_id or "").strip() or new_session_id()
    text = (user_message or "").strip()
    if not text:
        raise ValueError("请输入消息内容")

    history = await load_messages_async(
        sid, redis_client=redis_client, db_session=db_session
    )

    # —— 首轮 vs 强制刷新判断 ——
    has_prior_assistant = any(
        m.get("role") == "assistant" for m in history
    )
    # 强制刷新：勾选了任一开关 → 在后续轮中也算「数据载入轮」
    force_any = force_refresh and any(force_refresh.values())
    is_first_turn = (not has_prior_assistant and symbol) or (force_any and symbol)

    research_context: dict[str, Any] | None = None
    scan_context: dict[str, Any] | None = None

    if is_first_turn:
        research_context = await _ensure_research_context(
            db_session, symbol, redis_client=redis_client
        )
        if research_context is None and db_session is not None:
            scan_context = await _load_scan_context(db_session, symbol)
        # 仅在首轮或 jl13 开关打开时附加 JL1-3 模板
        append_jl13 = (not has_prior_assistant) or (force_refresh and force_refresh.get("jl13", False))
        text = compose_user_question(
            text,
            jl13_data_prompt=jl13_data_prompt or DEFAULT_JL13_DATA_TEMPLATE,
            include_jl13=append_jl13,
        )
    elif symbol:
        # 后续轮次：不附加 JL1–3，不注入数据包；仅提示历史中已有上下文
        pass

    if len(text) > _MAX_USER_CHARS:
        raise ValueError(f"消息过长（>{_MAX_USER_CHARS} 字）")

    history.append({"role": "user", "content": text})

    system_prompt = _build_system_for_turn(
        symbol=symbol,
        research_context=research_context,
        scan_context=scan_context,
        has_prior_assistant=has_prior_assistant,
        force_data=force_any and has_prior_assistant,
    )

    # —— 换标上下文切换：过滤旧 assistant 回复，防止 LLM 引用旧标分析 ——
    api_history = history
    if has_prior_assistant and force_any and symbol:
        # 只保留 system/user 消息，丢弃旧 assistant（LLM 会基于上下文切换指令重新分析新标）
        api_history = [m for m in history if m.get("role") != "assistant"]

    api_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]
    api_messages.extend(api_history)

    context_meta = summarize_context_meta(
        symbol=symbol,
        research_context=research_context,
        scan_context=scan_context,
        user_text=text,
        system_prompt=system_prompt,
        is_subsequent_turn=bool(has_prior_assistant and symbol and not force_any),
    )

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
        # AI 调用失败：先保存含用户消息的历史，避免刷新后对话丢失
        try:
            await save_messages_async(
                sid, history, redis_client=redis_client, db_session=db_session
            )
            if db_session is not None:
                await db_session.commit()
        except Exception:
            pass
        history.pop()
        return {
            "session_id": sid,
            "messages": history,
            "error": str(exc)[:300],
            "status": "error",
            "context_meta": context_meta,
        }

    if resp.model == "mock" or (resp.raw or {}).get("_dispatcher_mock"):
        # AI 返回 mock/不可达：保存用户消息避免丢失
        try:
            await save_messages_async(
                sid, history, redis_client=redis_client, db_session=db_session
            )
            if db_session is not None:
                await db_session.commit()
        except Exception:
            pass
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
            "context_meta": context_meta,
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
                "context_meta": context_meta,
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
        "context_meta": context_meta,
    }
