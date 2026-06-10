"""执行中工作区 · T2 持仓分析师（envelope 组装 + Opus 推理）。

[Ref: 28_ §5 · t2_preexec_envelope]
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.t1_assembler import assemble_batch_portfolio
from apps.copilot.modules.executing.t2_preexec_envelope import (
    build_executing_opus_messages,
    build_t2_preexec_envelope,
)
from apps.copilot.modules.executing.t2_token_limits import (
    inject_t2_output_budget,
    token_limits_summary,
    t2_max_output_tokens,
    validate_t2_opus_messages,
)
from apps.copilot.modules.radar.chat import chat_model_route, resolve_chat_model
from apps.copilot.modules.radar.schema import estimate_cost_yuan

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_TEMPLATE = (
    "请对当前组合做一次完整 T2 持仓审计，逐只评估工业富联、英维克、新易盛。\n"
    "【四层数据】\n"
    "· JL1 宏观、JL2 产业链、JL3 微观靶向：须补充真实市场数据（见下方 JL1–3 数据需求）；\n"
    "· JL4 资金博弈：只读本地 T1 indicators，禁止编造 indicators 未出现的数值。\n"
    "【交叉验证 JL1–JL4】\n"
    "逐标的写出四层推理链：JL1 宏观环境 → JL2 产业逻辑 → JL3 微观靶向 → JL4 资金博弈，\n"
    "说明各层支撑/冲突/降级关系；组合级 Reasoning_Engine 亦须覆盖四层。\n"
    "【操作建议】\n"
    "分别给出增持、减持、清仓、换股或继续观察；\n"
    "若涉及增减持须写明具体幅度（如增持至 X%、减持 30%、清仓 100%）和理由。\n"
    "【组合级】\n"
    "总结各标的近日需要重点关注的增、减、清仓相关的 JL1–4 中哪些关键指标的变化，以及如何应对。"
    "安全性优先于收益，逻辑链断裂时退出优先于追价；所有建议仅为 advisory，我人工会二次确认。"
)

DEFAULT_JL13_DATA_TEMPLATE = (
    "【JL1–JL3 公开市场数据补充要求】\n"
    "1. checklist 中 status=empty 的题，请基于真实市场/行业/公司公开信息主动检索并补全；\n"
    "2. 每只标的、每一层（JL1 宏观 / JL2 产业链 / JL3 微观靶向）至少给出 5 个可核验数据点"
    "（注明口径、时间范围、来源类型，如宏观统计/财报/行业研报/公司公告）；\n"
    "3. 有依据填 status=filled；部分推断填 status=partial 并说明置信度；完全无据才 empty；\n"
    "4. 禁止编造 JL4 indicators 未出现的数值；JL1–JL3 允许引用公开市场事实，不得捏造具体数字。"
)


def compose_user_question(
    question: str,
    *,
    jl13_data_prompt: str = "",
    include_jl13: bool = True,
) -> str:
    """合并组合审计问题与 JL1–3 数据补充要求。"""
    parts: list[str] = []
    q = (question or "").strip()
    if q:
        parts.append(q)
    if include_jl13:
        jl = (jl13_data_prompt or DEFAULT_JL13_DATA_TEMPLATE).strip()
        if jl and jl not in q:
            parts.append(jl)
    return "\n\n".join(parts)

_MAX_TURNS = 20
_REDIS_TTL_SEC = 7 * 24 * 3600
_memory_sessions: dict[str, list[dict[str, Any]]] = {}


def new_analyst_session_id() -> str:
    return uuid.uuid4().hex[:16]


def _redis_key(session_id: str) -> str:
    return f"executing:analyst:chat:{session_id}"


def _trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return messages[-_MAX_TURNS * 2 :]


def _load_messages_from_redis(redis_client: Any, session_id: str) -> list[dict[str, Any]] | None:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(_redis_key(session_id))
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, list):
            return [m for m in data if m.get("role") in ("user", "assistant")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 T2 分析会话 Redis 失败 sid=%s: %s", session_id, exc)
    return None


def _save_messages_to_redis(
    redis_client: Any, session_id: str, messages: list[dict[str, Any]]
) -> None:
    if redis_client is None:
        return
    try:
        redis_client.setex(
            _redis_key(session_id),
            _REDIS_TTL_SEC,
            json.dumps(_trim_messages(messages), ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入 T2 分析会话 Redis 失败 sid=%s: %s", session_id, exc)


async def rebuild_session_from_requests(
    db_session: AsyncSession,
    session_id: str,
) -> list[dict[str, Any]]:
    """从 PG 审计行按 session_id 重建对话（Redis/会话表缺失时的兜底）。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest
    from sqlalchemy import select

    sid = (session_id or "").strip()
    if not sid:
        return []

    rows = (
        await db_session.scalars(
            select(ExecutingT2AnalystRequest)
            .where(ExecutingT2AnalystRequest.session_id == sid)
            .order_by(ExecutingT2AnalystRequest.created_at.asc())
        )
    ).all()
    messages: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row.payload_json or {})
        payload.setdefault("request_id", row.request_id)
        payload.setdefault("user_question", row.user_question)
        payload.setdefault("symbols", row.symbols_json or [])
        payload.setdefault("model_id", row.model_id)
        payload.setdefault("include_t1_jl4", row.include_t1_jl4)
        preview_only = bool(payload.get("preview_only", row.dry_run))
        api_ok = bool(row.api_connected and payload.get("opus_audit"))
        if api_ok:
            assistant_content = format_opus_audit_summary(payload)
            status = "ok"
        elif payload.get("opus_error"):
            assistant_content = (
                format_assembly_summary(payload)
                + f"\n\n⚠️ Opus 失败: {payload.get('opus_error')}"
            )
            status = "error"
        else:
            assistant_content = format_assembly_summary(payload)
            status = "assembly_only"
        messages.append(
            {
                "role": "user",
                "content": row.user_question or "",
                "meta": {
                    "symbols": row.symbols_json or [],
                    "model_id": row.model_id,
                    "include_t1_jl4": row.include_t1_jl4,
                    "request_id": row.request_id,
                },
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "meta": {
                    "preview_only": preview_only,
                    "api_connected": bool(row.api_connected),
                    "payload": payload,
                    "request_id": row.request_id,
                    "status": status,
                    "error": payload.get("opus_error"),
                },
            }
        )
    return _trim_messages(messages)


async def load_analyst_messages(
    session_id: str,
    *,
    redis_client: Any = None,
    db_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """加载 T2 分析对话：内存 → Redis → PG 会话表 → 审计行重建。"""
    sid = (session_id or "").strip()
    if not sid or sid == "placeholder":
        return []

    cached = _memory_sessions.get(sid)
    if cached:
        return list(cached)

    redis_msgs = _load_messages_from_redis(redis_client, sid)
    if redis_msgs is not None:
        _memory_sessions[sid] = redis_msgs
        return list(redis_msgs)

    if db_session is not None:
        from apps.copilot.db.models import ExecutingT2AnalystSession
        from sqlalchemy import select

        row = await db_session.scalar(
            select(ExecutingT2AnalystSession).where(
                ExecutingT2AnalystSession.session_id == sid
            )
        )
        if row and row.messages_json:
            msgs = _trim_messages(list(row.messages_json))
            _memory_sessions[sid] = msgs
            _save_messages_to_redis(redis_client, sid, msgs)
            return list(msgs)

        rebuilt = await rebuild_session_from_requests(db_session, sid)
        if rebuilt:
            _memory_sessions[sid] = rebuilt
            _save_messages_to_redis(redis_client, sid, rebuilt)
            await persist_analyst_session(db_session, sid, rebuilt)
            return list(rebuilt)

    return []


async def persist_analyst_session(
    db_session: AsyncSession,
    session_id: str,
    messages: list[dict[str, Any]],
) -> None:
    """PG 持久化 T2 分析会话（Redis 热缓存的权威底库）。"""
    from apps.copilot.db.models import ExecutingT2AnalystSession
    from sqlalchemy import select

    sid = (session_id or "").strip()
    if not sid:
        return
    trimmed = _trim_messages(messages)
    row = await db_session.scalar(
        select(ExecutingT2AnalystSession).where(ExecutingT2AnalystSession.session_id == sid)
    )
    if row is None:
        row = ExecutingT2AnalystSession(session_id=sid, messages_json=trimmed)
        db_session.add(row)
    else:
        row.messages_json = trimmed
    await db_session.flush()


async def clear_analyst_session(
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
        from apps.copilot.db.models import ExecutingT2AnalystSession
        from sqlalchemy import delete

        await db_session.execute(
            delete(ExecutingT2AnalystSession).where(
                ExecutingT2AnalystSession.session_id == sid
            )
        )
        await db_session.flush()


async def warm_t2_analyst_sessions_from_pg(
    db_session: AsyncSession,
    redis_client: Any,
    *,
    limit: int = 50,
) -> dict[str, int]:
    """Pod 启动时从 PG 回填 T2 分析对话 Redis 热缓存。"""
    if not redis_client:
        return {"sessions": 0, "warmed": 0, "skipped": "no_redis"}

    from apps.copilot.db.models import ExecutingT2AnalystSession
    from sqlalchemy import select

    rows = (
        await db_session.scalars(
            select(ExecutingT2AnalystSession)
            .order_by(ExecutingT2AnalystSession.updated_at.desc())
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
    logger.info("T2 分析会话 Redis 预热 sessions=%d warmed=%d", len(rows), warmed)
    return {"sessions": len(rows), "warmed": warmed}


async def list_t2_analyst_sessions(
    db_session: AsyncSession,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    from apps.copilot.db.models import ExecutingT2AnalystSession
    from apps.copilot.modules.radar.chat import title_from_messages
    from sqlalchemy import select

    rows = (
        await db_session.scalars(
            select(ExecutingT2AnalystSession)
            .order_by(ExecutingT2AnalystSession.updated_at.desc())
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
                "title": title_from_messages(msgs, default="新分析"),
                "updatedAt": ts,
            }
        )
    return out


async def save_analyst_messages(
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
        await persist_analyst_session(db_session, sid, trimmed)


def strip_jl4_from_t1(t1_payload: dict[str, Any]) -> dict[str, Any]:
    """移除 JL4 indicators，保留 position_context 与 batch_meta。"""
    out = copy.deepcopy(t1_payload)
    for sig in (out.get("portfolio_signals") or {}).values():
        sig["indicators"] = {}
        if "degraded_probes" in sig:
            sig["degraded_probes"] = [
                d for d in (sig.get("degraded_probes") or [])
                if "tech_beta" not in str(d).lower()
            ] or None
    return out


def t2_opus_enabled() -> bool:
    if os.environ.get("EXECUTING_T2_ANALYST_PREVIEW_ONLY", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    if os.environ.get("EXECUTING_T2_ENABLED", "").lower() not in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


async def assemble_t2_analyst_payload(
    session: AsyncSession,
    symbols: list[str],
    *,
    user_question: str,
    model_id: str | None,
    include_t1_jl4: bool,
    jl13_data_prompt: str = "",
    include_jl13_data: bool = True,
    redis_client: Any = None,
) -> dict[str, Any]:
    """组装 T2 预执行 envelope 与 Opus messages。"""
    syms = [s.zfill(6)[-6:] for s in symbols if s and str(s).strip()]
    if not syms:
        raise ValueError("请至少选择一个标的")

    t1 = await assemble_batch_portfolio(session, syms, redis_client=redis_client)
    if not include_t1_jl4:
        t1 = strip_jl4_from_t1(t1)

    envelope = build_t2_preexec_envelope(t1)
    messages = build_executing_opus_messages(envelope)
    inject_t2_output_budget(envelope, messages, symbol_count=len(syms))
    resolved_model = resolve_chat_model(model_id)

    composed_question = compose_user_question(
        user_question,
        jl13_data_prompt=jl13_data_prompt,
        include_jl13=include_jl13_data,
    )

    user_body = json.loads(messages[1]["content"])
    user_body["model_id"] = resolved_model
    user_body["include_t1_jl4"] = include_t1_jl4
    user_body["include_jl13_data"] = include_jl13_data
    user_body["jl13_data_prompt"] = (jl13_data_prompt or "").strip() or None
    user_body["user_question"] = composed_question
    messages[1]["content"] = json.dumps(user_body, ensure_ascii=False)

    if composed_question:
        profit = user_body.get("profit") or {}
        pos_hint = json.dumps(profit.get("positions") or {}, ensure_ascii=False)[:1200]
        messages[0]["content"] = (
            messages[0]["content"]
            + "\n\n## 用户本轮关键词问题\n"
            + composed_question
            + "\n\n## 当前持仓（holding_honesty 须基于此，禁止写「今日首次建仓」）\n"
            + pos_hint
            + "\n须优先回应 user_question，并严格按 output_contract 输出单个 JSON；"
            + "总篇幅不得超过 output_contract.max_output_tokens。"
        )

    jl4_counts = {
        key: len(sig.get("indicators") or {})
        for key, sig in (t1.get("portfolio_signals") or {}).items()
    }

    token_limits = token_limits_summary()
    input_stats = validate_t2_opus_messages(messages)

    return {
        "preview_only": not t2_opus_enabled(),
        "api_connected": False,
        "model_id": resolved_model,
        "include_t1_jl4": include_t1_jl4,
        "user_question": composed_question,
        "jl13_data_prompt": user_body.get("jl13_data_prompt"),
        "include_jl13_data": include_jl13_data,
        "symbols": list((t1.get("portfolio_signals") or {}).keys()),
        "jl4_indicator_counts": jl4_counts,
        "envelope": envelope,
        "opus_messages": messages,
        "token_limits": token_limits,
        "input_stats": input_stats,
    }


def _parse_opus_audit_json(text: str) -> dict[str, Any]:
    """解析 Opus T2 输出 JSON；容忍 ``` 围栏与末尾多余字符。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return {"raw_text": ""}
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    if start < 0:
        return {"raw_text": text[:4000]}

    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(cleaned, start)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    end = cleaned.rfind("}") + 1
    if end > start:
        chunk = cleaned[start:end]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            for trim in range(1, 6):
                try:
                    return json.loads(chunk[:-trim])
                except json.JSONDecodeError:
                    continue
    return {"raw_text": text[:4000]}


def _is_transient_opus_error(exc: BaseException) -> bool:
    from apps.common.ai_dispatcher import is_transient_anthropic_error

    return is_transient_anthropic_error(exc)


async def invoke_t2_opus_audit(
    opus_messages: list[dict[str, str]],
    *,
    model_id: str,
) -> dict[str, Any]:
    """调用 Opus 完成 T2 持仓审计。"""
    import time as _time

    input_stats = validate_t2_opus_messages(opus_messages)
    max_out = t2_max_output_tokens()
    t0 = _time.perf_counter()

    route = chat_model_route(model_id)

    def _blocking() -> Any:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        try:
            return AIDispatcher.default().call(
                "radar_assess",
                opus_messages,
                max_tokens=max_out,
                temperature=0.2,
                force_route=route,
                model_override=model_id,
            )
        except BudgetExceededError as exc:
            raise RuntimeError(f"日预算上限：{exc}") from exc

    try:
        resp = await asyncio.to_thread(_blocking)
    except RuntimeError as exc:
        elapsed = int((_time.perf_counter() - t0) * 1000)
        raise RuntimeError(f"{exc} [failed_after_ms={elapsed}]") from exc
    if resp.model == "mock" or (resp.raw or {}).get("_dispatcher_mock"):
        if route == "deepseek":
            raise RuntimeError(
                "DeepSeek 调用失败（请检查 DEEPSEEK_API_KEY 有效性或账户余额）"
            )
        raise RuntimeError(
            "Opus 不可达（请配置 ANTHROPIC_API_KEY / ANTHROPIC_HTTPS_PROXY）"
        )

    text = (resp.text or "").strip() or "{}"
    audit = _parse_opus_audit_json(text)
    parse_ok = bool(
        isinstance(audit, dict)
        and (audit.get("Execution_Command") or audit.get("symbol_audits"))
    )
    cost = estimate_cost_yuan(resp.tokens_in, resp.tokens_out)
    if resp.cost_yuan_est and resp.cost_yuan_est > 0:
        cost = resp.cost_yuan_est

    raw = resp.raw or {}
    stop_reason = raw.get("stop_reason") or ""
    truncated = stop_reason == "max_tokens" or resp.tokens_out >= int(max_out * 0.98)

    return {
        "audit": audit,
        "meta": {
            "model": resp.model or model_id,
            "route": resp.route,
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "cost_yuan": cost,
            "latency_ms": resp.latency_ms,
            "stop_reason": stop_reason,
            "truncated": truncated,
            "max_output_tokens": max_out,
            "input_chars": input_stats.get("input_chars"),
            "parse_ok": parse_ok,
        },
        "raw_text": text[:64_000],
    }


def format_assembly_summary(payload: dict[str, Any]) -> str:
    """仅拼接 envelope、未调用模型时的摘要。"""
    reason = payload.get("opus_skip_reason") or "模型未启用或缺少 API Key"
    syms = ", ".join(payload.get("symbols") or [])
    return (
        f"数据已准备完毕，尚未调用模型分析。\n"
        f"原因：{reason}\n"
        f"标的：{syms or '—'}"
    )


def format_opus_audit_summary(payload: dict[str, Any]) -> str:
    """模型推理完成后的对话区纯文本摘要（中文）。"""
    from apps.copilot.modules.executing.t2_analyst_render import extract_t2_prose_text

    prose = extract_t2_prose_text(payload)
    if prose:
        return prose
    audit = payload.get("opus_audit") or {}
    cmd = audit.get("Execution_Command") or {}
    return (cmd.get("one_sentence_summary") or "").strip() or "分析已完成，详见审计页。"


async def persist_t2_analyst_request(
    session: AsyncSession,
    *,
    session_id: str,
    payload: dict[str, Any],
    request_id: str | None = None,
) -> str:
    """持久化 T2 完整数据集（拼接 + Opus 回复 + 渲染 HTML）供审计查阅。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest

    rid = (request_id or "").strip() or uuid.uuid4().hex[:16]
    preview_only = bool(payload.get("preview_only", True))
    row = ExecutingT2AnalystRequest(
        request_id=rid,
        session_id=(session_id or "").strip() or None,
        user_question=str(payload.get("user_question") or ""),
        model_id=payload.get("model_id"),
        include_t1_jl4=bool(payload.get("include_t1_jl4")),
        symbols_json=list(payload.get("symbols") or []),
        dry_run=preview_only,
        api_connected=bool(payload.get("api_connected", False)),
        payload_json=payload,
    )
    session.add(row)
    await session.flush()
    return rid


async def analyst_chat_turn(
    session: AsyncSession,
    *,
    session_id: str,
    symbols: list[str],
    user_question: str,
    model_id: str | None,
    include_t1_jl4: bool,
    jl13_data_prompt: str = "",
    include_jl13_data: bool = True,
    redis_client: Any = None,
    progress_cb: Any = None,
) -> dict[str, Any]:
    """T2 多轮对话：组装 envelope → 调用 Opus（已启用时）→ 存档。"""
    sid = (session_id or "").strip() or new_analyst_session_id()
    if sid == "placeholder":
        sid = new_analyst_session_id()
    question = (user_question or "").strip()
    if not question:
        raise ValueError("请输入关键词或提示词问题")

    if progress_cb:
        progress_cb("assemble", 15, "组装 JL4 envelope 与公开市场数据…")

    payload = await assemble_t2_analyst_payload(
        session,
        symbols,
        user_question=question,
        model_id=model_id,
        include_t1_jl4=include_t1_jl4,
        jl13_data_prompt=jl13_data_prompt,
        include_jl13_data=include_jl13_data,
        redis_client=redis_client,
    )

    status = "assembly_only"
    assistant_content = ""
    opus_error: str | None = None

    if t2_opus_enabled():
        if progress_cb:
            progress_cb(
                "opus",
                35,
                "Opus 审计中（经新加坡出口代理 · 完整审计约 3～5 分钟）…",
            )
        try:
            opus_result = await invoke_t2_opus_audit(
                payload["opus_messages"],
                model_id=payload["model_id"],
            )
            payload["opus_audit"] = opus_result["audit"]
            payload["opus_meta"] = opus_result["meta"]
            payload["opus_raw_text"] = opus_result.get("raw_text")
            payload["preview_only"] = False
            payload["api_connected"] = True
            assistant_content = format_opus_audit_summary(payload)
            status = "ok"
        except Exception as exc:  # noqa: BLE001
            logger.exception("T2 Opus analyst failed")
            opus_error = str(exc)[:400]
            payload["opus_error"] = opus_error
            payload["preview_only"] = True
            payload["api_connected"] = False
            assistant_content = format_assembly_summary(payload) + f"\n\n⚠️ Opus 失败: {opus_error}"
            status = "error"
    else:
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            payload["opus_skip_reason"] = "ANTHROPIC_API_KEY 未配置"
        elif os.environ.get("EXECUTING_T2_ENABLED", "").lower() not in (
            "1",
            "true",
            "yes",
        ):
            payload["opus_skip_reason"] = "EXECUTING_T2_ENABLED 未开启"
        else:
            payload["opus_skip_reason"] = "EXECUTING_T2_ANALYST_PREVIEW_ONLY=1"
        assistant_content = format_assembly_summary(payload)
        status = "assembly_only"

    request_id = uuid.uuid4().hex[:16]
    payload["request_id"] = request_id
    assistant_meta = {
        "preview_only": payload.get("preview_only", True),
        "api_connected": payload.get("api_connected", False),
        "request_id": request_id,
        "status": status,
        "error": opus_error,
    }
    from apps.copilot.modules.executing.t2_analyst_render import render_t2_chat_prose

    payload["assistant_render_html"] = render_t2_chat_prose(payload, assistant_meta)

    if progress_cb:
        progress_cb("persist", 92, "写入审计与会话历史…")

    await persist_t2_analyst_request(
        session, session_id=sid, payload=payload, request_id=request_id
    )

    messages = await load_analyst_messages(sid, redis_client=redis_client, db_session=session)
    messages.append(
        {
            "role": "user",
            "content": question,
            "meta": {
                "symbols": payload.get("symbols"),
                "model_id": payload.get("model_id"),
                "include_t1_jl4": payload.get("include_t1_jl4"),
                "request_id": request_id,
            },
        }
    )
    messages.append(
        {
            "role": "assistant",
            "content": assistant_content,
            "meta": {
                "preview_only": payload.get("preview_only", True),
                "api_connected": payload.get("api_connected", False),
                "payload": payload,
                "request_id": request_id,
                "status": status,
                "error": opus_error,
            },
        }
    )
    await save_analyst_messages(
        sid, messages, redis_client=redis_client, db_session=session
    )
    await session.commit()
    return {
        "session_id": sid,
        "request_id": request_id,
        "messages": messages,
        "payload": payload,
        "status": status,
        "error": opus_error,
    }


async def run_t2_analyst_job(
    job_id: str,
    *,
    session_id: str,
    symbols: list[str],
    user_question: str,
    model_id: str | None,
    include_t1_jl4: bool,
    jl13_data_prompt: str,
    include_jl13_data: bool,
    redis_client: Any,
) -> None:
    """后台执行 T2 分析（独立 DB 会话 · Redis 进度供 HTMX 轮询）。"""
    from apps.copilot.db.database import AsyncSessionLocal
    from apps.copilot.modules.executing.t2_analyst_progress import (
        fail_job,
        finish_job,
        make_progress_callback,
    )

    cb = make_progress_callback(redis_client, job_id)
    async with AsyncSessionLocal() as session:
        try:
            result = await analyst_chat_turn(
                session,
                session_id=session_id,
                symbols=symbols,
                user_question=user_question,
                model_id=model_id,
                include_t1_jl4=include_t1_jl4,
                jl13_data_prompt=jl13_data_prompt,
                include_jl13_data=include_jl13_data,
                redis_client=redis_client,
                progress_cb=cb,
            )
            await session.commit()
            finish_job(redis_client, job_id, result)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("T2 analyst job %s failed", job_id)
            fail_job(redis_client, job_id, str(exc)[:500])
