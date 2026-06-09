"""T2 预执行完全体 envelope 构建（哲学背景 + 输入契约 + 输出 Schema）。

[Ref: 28_ §4.1 · §5 · 06_投资哲学体系总纲]
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from apps.copilot.modules.executing.probe_keys import PROBE_KEYS
from apps.copilot.modules.executing.probe_labels import probe_label
from apps.copilot.modules.executing.profile import (
    load_profile,
    profile_expected_probe_count,
    profile_l3_keys,
)

ENVELOPE_VERSION = "executing_t2_preexec_v2"

# 共享 JL1 问题槽（不占 JL3 探针行 · 28_ §2.1）
SHARED_JL1_TOPICS: tuple[dict[str, str], ...] = (
    {"topic_id": "liquidity_regime", "question": "A股/港股流动性对高 beta 科技股的影响？"},
    {"topic_id": "ai_capex_cycle", "question": "全球 AI Capex 扩张/放缓/拐点？"},
    {"topic_id": "trade_policy", "question": "贸易/关税对出口链 ODM 与光模块的影响？"},
)

RADAR_OPTIONAL_TOPICS: tuple[dict[str, str], ...] = (
    {"topic_id": "nvda_gpu_leadtime", "layer": "JL2", "question": "NVIDIA GPU 交期与供给瓶颈？"},
    {"topic_id": "tsmc_cowos_capacity", "layer": "JL2", "question": "TSMC CoWoS 产能与扩产节奏？"},
    {"topic_id": "cloud_capex_consensus", "layer": "JL2", "question": "四云 Capex 共识与修正方向？"},
    {"topic_id": "cpi_ppi_spread", "layer": "JL1", "question": "CPI-PPI 剪刀差与宏观流动性？"},
)

PROFILE_JL2_TOPICS: dict[str, tuple[dict[str, str], ...]] = {
    "601138": (
        {"topic_id": "ai_server_odm", "question": "AI 服务器 ODM 格局与订单能见度？"},
        {"topic_id": "gb200_chain", "question": "GB200 产业链放量节奏？"},
        {"topic_id": "gpu_cowos", "question": "GPU/CoWoS 供给约束？"},
    ),
    "002837": (
        {"topic_id": "liquid_cooling", "question": "液冷渗透率与集采格局？"},
        {"topic_id": "metal_cost", "question": "铜铝成本对 CDU 毛利？"},
    ),
    "300502": (
        {"topic_id": "optical_gen", "question": "1.6T/3.2T 光模块代际竞争？"},
        {"topic_id": "dsp_supply", "question": "DSP/激光器供给瓶颈？"},
    ),
}

# JL4：每个 probe_key 对应的核心问题（解读 indicators 时在 jl4_read 回答）
JL4_CORE_QUESTIONS: dict[str, str] = {
    "qmt_atr_trailing": "从峰值回撤几倍 ATR？利润是否该锁？",
    "volume_price_div": "高位是否在放量下跌/量价背离？",
    "smart_money_flow": "近3日主力净流入还是流出？",
    "level2_super_order": "特大单动能处于历史什么分位？",
    "margin_short_skew": "融资杠杆是否异常偏高？",
    "turnover_acceleration": "换手相对基线是否异常放大？",
    "block_trade_discount": "大宗折价与盘口冲击如何？",
    "retail_concentration": "筹码是否散户化/分散？",
    "insider_sell_actual": "内部人是否在减持？",
    "etf_redemption_impact": "关联 ETF 申赎有无被动冲击？",
    "tech_beta_correlation": "与板块指数联动多强？是否独立走弱？",
}

JL_REPLY_FIELDS = {"status": "filled|empty", "answer": "有据简述；无据留空"}
JL4_REPLY_FIELDS = {"key": "probe_key", "reading": "基于 value+fact_statement 的客观解读"}


def _sym_to_profile_id(symbol: str) -> str:
    return re.sub(r"\.(SH|SZ)$", "", symbol.upper())


def _attach_reply(item: dict[str, str], *, layer: str, match: str) -> dict[str, Any]:
    """为输入问题项标注期待回复槽位。"""
    out: dict[str, Any] = dict(item)
    out["reply"] = {
        "path": f"symbol_audits.{{symbol}}.{layer}",
        "match": match,
        "fields": dict(JL_REPLY_FIELDS),
    }
    return out


def compile_system_prompt() -> str:
    lines = [
        "你是执行中工作区首席持仓分析师，负责对真实持仓做利润保卫与调仓建议。",
        "",
        "## 哲学判据",
        "- 价值三角：安全性 > 确定性 > 收益率；本金不可逆，逻辑链断则退出优先于追收益。",
        "- 赚认知差，不赚价格波动差；事实断言需多源印证，禁止单源脑补。",
        "- 持仓诚实（holding_honesty）：针对 profit.positions 已有仓位（含 entry_date、成本、股数、浮盈），"
        "须回答：①建议加仓/维持/减持及具体幅度 ②剩余可用资金是否还会买入 ③关键理由；"
        "禁止写「今日首次建仓/首次出现」——用户已持仓。",
        "- 卖出=逻辑前提改变时的退出，不是裸价格止损。",
        "",
        "## 数据地图",
        "- JL1 宏观 / JL2 产业链 / JL3 微观靶向：checklist 题为骨架；输入 status=empty 时，"
        "须基于公开市场事实主动补全（宏观统计、行业数据、财报、公告等），每层每标的至少 5 个可核验数据点；",
        "answer 内注明口径/时间/来源类型；有据填 filled，部分推断填 partial，完全无据才 empty。",
        "- JL4 资金博弈：只读 t1.portfolio_signals.*.indicators；禁止编造 indicators 未出现的数值。",
        "",
        "## 问答路由",
        "- 输入问题见 checklist/optional/jl4_catalog，每项带 reply 路径。",
        "- 输出严格按 output_contract.example 填；组合动作写 Execution_Command，单票写 symbol_audits。",
        "- trim/dump 时 Execution_Command.targets 必须列出受影响标的。",
        "",
        "## 交叉验证（JL1–JL4 四层，禁止只写 JL3×JL4）",
        "- symbol_audits.cross_validation 与 Reasoning_Engine.cross_validation_logic 须按"
        "JL1→JL2→JL3→JL4 顺序写推理链，标明各层支撑/冲突/降级",
        "- JL1/JL2/JL3 完好 + JL4 量价背离/主力流出 → 事出反常，倾向减仓/清仓",
        "- JL4 ATR 未破界碑 + JL1–JL3 无 blocker → 持有",
        "- JL1–JL3 大面积 empty 且仅 JL4 有数 → 须标明「降级：仅 JL4 可置信」",
        "",
        "## 输出铁律",
        "- 仅一个 JSON，字段覆盖 output_contract.required",
        "- action：hold|trim_30_pct|dump_all|rotate|watch",
        "- JL4：禁止编造 indicators 未出现的数值",
        "- JL1–JL3：允许引用公开市场事实，禁止捏造；不确定用 partial",
        "- Executing_Daily_Audit.L3/L4 须按标的分段：每只以「简称：」起句；"
        "浮盈/浮亏必须写在该标的句内，禁止组合加总或串标的",
    ]
    return "\n".join(lines)


def _jl3_topics_from_profile(profile_id: str) -> list[dict[str, Any]]:
    prof = load_profile(profile_id)
    l3 = prof.get("l3_probes") or {}
    topics: list[dict[str, Any]] = []
    for key in profile_l3_keys(prof):
        meta = l3.get(key) or {}
        label = meta.get("label") or key
        rc = meta.get("reading_class") or ""
        question = f"{label}是否仍健康？" if not rc else f"{label}（{rc}）是否仍健康？"
        topics.append(
            _attach_reply({"key": key, "question": question}, layer="jl3", match="key")
        )
    return topics


def build_supplement_checklist(portfolio_signals: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for symbol, sig in portfolio_signals.items():
        pid = _sym_to_profile_id(symbol)
        prof = load_profile(pid)
        out[symbol] = {
            "name": sig.get("stock_name") or prof.get("name") or pid,
            "jl1": [
                _attach_reply(dict(t), layer="jl1", match="topic_id") for t in SHARED_JL1_TOPICS
            ],
            "jl2": [
                _attach_reply(dict(t), layer="jl2", match="topic_id")
                for t in PROFILE_JL2_TOPICS.get(pid, ())
            ],
            "jl3": _jl3_topics_from_profile(pid),
        }
    return out


def build_optional_context() -> dict[str, Any]:
    jl1: list[dict[str, Any]] = []
    jl2: list[dict[str, Any]] = []
    for t in RADAR_OPTIONAL_TOPICS:
        layer = "jl1" if t["layer"] == "JL1" else "jl2"
        entry = _attach_reply(
            {
                "topic_id": t["topic_id"],
                "question": t["question"],
                "snapshot": None,
                "status": "empty",
            },
            layer=layer,
            match="topic_id",
        )
        if t["layer"] == "JL1":
            jl1.append(entry)
        else:
            jl2.append(entry)
    return {"radar_jl1": jl1, "radar_jl2": jl2, "planning_artifact": None}


def build_jl4_catalog(portfolio_signals: dict[str, Any]) -> dict[str, Any]:
    """逐标的 JL4：输入数据路径 + 核心问题 + 期待回复槽位。"""
    per_symbol: dict[str, Any] = {}
    for symbol, sig in portfolio_signals.items():
        indicators = sig.get("indicators") or {}
        probes: list[dict[str, Any]] = []
        for key in PROBE_KEYS:
            present = key in indicators
            probes.append(
                {
                    "key": key,
                    "label": probe_label(key),
                    "question": JL4_CORE_QUESTIONS.get(key, ""),
                    "input": (
                        f"t1.portfolio_signals.{symbol}.indicators.{key}"
                        if present
                        else None
                    ),
                    "present": present,
                    "reply": {
                        "path": f"symbol_audits.{symbol}.jl4_read",
                        "match": "key",
                        "fields": dict(JL4_REPLY_FIELDS),
                    },
                }
            )
        per_symbol[symbol] = probes
    return {"per_symbol": per_symbol}


def build_qa_index() -> list[dict[str, Any]]:
    """组合级关键问题 → 回复路径一览（检验用）。"""
    return [
        {
            "id": "portfolio_action",
            "asks": "组合整体：持有/减30%/清仓/换股/观察？",
            "reply_path": "Execution_Command.action",
            "reply_enum": ["hold", "trim_30_pct", "dump_all", "rotate", "watch"],
        },
        {
            "id": "portfolio_targets",
            "asks": "若减仓或清仓，具体作用于哪几只、幅度多少？",
            "reply_path": "Execution_Command.targets[]",
            "reply_fields": {
                "symbol": "代码",
                "advice": "hold|trim|dump|watch",
                "pct_change": "如 -30% / -100%",
                "rationale": "一句话理由",
            },
        },
        {
            "id": "portfolio_summary",
            "asks": "一句话执行建议",
            "reply_path": "Execution_Command.one_sentence_summary",
            "reply_type": "string",
        },
        {
            "id": "stop_line",
            "asks": "止盈/止损界碑（基于 ATR 等 JL4）",
            "reply_path": "Execution_Command.stop_loss_line",
            "reply_type": "string",
        },
        {
            "id": "l3_verdict",
            "asks": "组合基本面（JL3 综合）",
            "reply_path": "Executing_Daily_Audit.L3_Fundamental_Verdict",
            "reply_type": "string",
        },
        {
            "id": "l4_verdict",
            "asks": "组合资金博弈（JL4 综合）",
            "reply_path": "Executing_Daily_Audit.L4_Microstructure_Verdict",
            "reply_type": "string",
        },
        {
            "id": "cross_logic",
            "asks": "JL1–JL4 四层交叉推理链（宏观→产业→微观→资金博弈）",
            "reply_path": "Reasoning_Engine.cross_validation_logic",
            "reply_type": "string",
        },
        {
            "id": "per_symbol_cross",
            "asks": "单票 JL1–JL4 四层交叉验证",
            "reply_path": "symbol_audits.{symbol}.cross_validation",
            "reply_type": "string",
        },
        {
            "id": "holding_honesty",
            "asks": "已持仓：建议加仓/维持/减持及幅度？剩余资金是否买入？关键理由？",
            "reply_path": "symbol_audits.{symbol}.holding_honesty",
            "reply_type": "string",
            "reply_format": "仓位调整+剩余资金是否买入+关键理由（禁止写首次建仓）",
        },
        {
            "id": "jl13_market_data",
            "asks": "JL1/JL2/JL3 每层每标的至少 5 个公开市场数据点",
            "reply_path": "symbol_audits.{symbol}.jl1|jl2|jl3",
            "reply_type": "checklist_filled",
        },
        {
            "id": "per_symbol_advice",
            "asks": "单票近期：持有/减仓/清仓/观察？",
            "reply_path": "symbol_audits.{symbol}.near_term_advice",
            "reply_enum": ["hold", "trim", "dump", "watch"],
        },
    ]


def _parse_pct(s: Any) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.match(r"^([\d.]+)\s*%?$", str(s).strip())
    return float(m.group(1)) if m else None


def build_profit_context(t1_payload: dict[str, Any]) -> dict[str, Any]:
    meta = t1_payload.get("batch_meta") or {}
    signals = t1_payload.get("portfolio_signals") or {}
    pcts: list[float] = []
    per_symbol: dict[str, Any] = {}
    for symbol, sig in signals.items():
        pos = sig.get("position_context") or {}
        pct = _parse_pct(pos.get("position_pct"))
        if pct is not None:
            pcts.append(pct)
        per_symbol[symbol] = {
            "unrealized_profit_pct": pos.get("unrealized_profit_pct"),
            "position_pct": pos.get("position_pct"),
            "cost_basis": pos.get("cost_basis"),
            "current_price": pos.get("current_price"),
            "holding_volume": pos.get("holding_volume"),
        }
    total_pct = round(sum(pcts), 2) if pcts else None
    return {
        "cash": meta.get("account_available_cash"),
        "money_unit": meta.get("money_unit", "人民币"),
        "system_status": meta.get("system_status"),
        "total_position_pct": f"{total_pct}%" if total_pct is not None else None,
        "positions": per_symbol,
    }


def build_t1_coverage(t1_payload: dict[str, Any]) -> dict[str, Any]:
    signals = t1_payload.get("portfolio_signals") or {}
    per_symbol: list[dict[str, Any]] = []
    total_expected = 0
    total_jl4_present = 0
    all_missing: list[str] = []
    for symbol, sig in signals.items():
        pid = _sym_to_profile_id(symbol)
        prof = load_profile(pid)
        indicators = sig.get("indicators") or {}
        jl4_keys = [k for k in PROBE_KEYS if k in indicators]
        jl4_missing = [k for k in PROBE_KEYS if k not in indicators]
        exp = profile_expected_probe_count(prof)
        total_expected += exp
        total_jl4_present += len(jl4_keys)
        all_missing.extend(jl4_missing)
        per_symbol.append(
            {
                "symbol": symbol,
                "jl4": f"{len(jl4_keys)}/{len(PROBE_KEYS)}",
                "total": exp,
                "missing": jl4_missing,
                "degraded": sig.get("degraded_probes"),
            }
        )
    return {
        "symbols": per_symbol,
        "rollup": {
            "symbols_count": len(signals),
            "jl4_present": total_jl4_present,
            "jl4_expected": len(signals) * len(PROBE_KEYS),
            "missing_unique": sorted(set(all_missing)),
        },
    }


def _symbol_audit_example(
    symbol: str,
    checklist_entry: dict[str, Any],
    indicator_keys: list[str],
) -> dict[str, Any]:
    return {
        "jl1": [
            {"topic_id": t["topic_id"], "status": "empty", "answer": ""}
            for t in checklist_entry.get("jl1", [])
        ],
        "jl2": [
            {"topic_id": t["topic_id"], "status": "empty", "answer": ""}
            for t in checklist_entry.get("jl2", [])
        ],
        "jl3": [
            {"key": t["key"], "status": "empty", "answer": ""}
            for t in checklist_entry.get("jl3", [])
        ],
        "jl4_read": [{"key": k, "reading": ""} for k in indicator_keys],
        "cross_validation": "",
        "near_term_advice": "hold",
        "holding_honesty": "",
    }


def build_output_contract(
    t1_payload: dict[str, Any],
    coverage: dict[str, Any],
    checklist: dict[str, Any],
) -> dict[str, Any]:
    signals = t1_payload.get("portfolio_signals") or {}
    symbol_audits: dict[str, Any] = {}
    targets: list[dict[str, str]] = []
    for symbol, sig in signals.items():
        indicators = sig.get("indicators") or {}
        # example 列出全部 JL4 key；present=false 时 reading 须留空
        keys = [k for k in PROBE_KEYS if k in indicators]
        missing = [k for k in PROBE_KEYS if k not in indicators]
        cl = checklist.get(symbol, {})
        audit = _symbol_audit_example(symbol, cl, keys)
        for k in missing:
            audit["jl4_read"].append({"key": k, "reading": "", "skipped": "input_missing"})
        symbol_audits[symbol] = audit
        targets.append(
            {
                "symbol": symbol,
                "advice": "hold",
                "pct_change": "0%",
                "rationale": "",
            }
        )
    rollup = coverage.get("rollup", {})
    return {
        "required": [
            "Executing_Daily_Audit",
            "Reasoning_Engine",
            "Execution_Command",
            "probe_coverage",
            "portfolio_synthesis",
            "symbol_audits",
        ],
        "rules": [
            "checklist/optional 每题 → symbol_audits 同 match 字段填 status+answer",
            "JL1/JL2/JL3：每层每标的 answer 合计至少 5 个可核验数据点；允许公开市场补全；status=filled|partial|empty",
            "holding_honesty：已持仓场景，写加仓/维持/减持+剩余资金是否买入+理由；禁止「今日首次建仓」",
            "cross_validation：单票须 JL1→JL2→JL3→JL4 四层推理链；组合级 cross_validation_logic 同理",
            "jl4_catalog.present=true 的 key → symbol_audits.jl4_read 必填 reading",
            "jl4_catalog.present=false 的 key → 禁止编造 reading，在 probe_coverage 说明",
            "Execution_Command.action 与 targets[].advice 须一致",
            "near_term_advice 与 targets[].advice 须一致",
        ],
        "example": {
            "Executing_Daily_Audit": {
                "L3_Fundamental_Verdict": "",
                "L4_Microstructure_Verdict": "",
            },
            "Reasoning_Engine": {
                "signal_conflicts": "",
                "cross_validation_logic": "",
            },
            "Execution_Command": {
                "action": "hold",
                "targets": targets,
                "stop_loss_line": "",
                "one_sentence_summary": "",
            },
            "probe_coverage": {
                "expected": rollup.get("jl4_expected", 0),
                "filled": rollup.get("jl4_present", 0),
                "missing": rollup.get("missing_unique", []),
                "blockers": [],
                "integrity_note": "",
            },
            "portfolio_synthesis": {
                "battlefield_allocation_note": "",
                "cross_symbol_conflicts": [],
                "portfolio_action_bias": "hold",
            },
            "symbol_audits": symbol_audits,
        },
    }


def build_executing_opus_messages(envelope: dict[str, Any]) -> list[dict[str, str]]:
    up = envelope["user_payload"]
    user_body = {
        "qa_index": envelope["qa_index"],
        "t1": up["t1"],
        "profit": up["profit"],
        "optional": up["optional"],
        "checklist": up["checklist"],
        "jl4_catalog": up["jl4_catalog"],
        "output_contract": envelope["output_contract"],
        "coverage": envelope["coverage"],
    }
    return [
        {"role": "system", "content": envelope["system_prompt"]},
        {"role": "user", "content": json.dumps(user_body, ensure_ascii=False)},
    ]


def build_t2_preexec_envelope(t1_payload: dict[str, Any]) -> dict[str, Any]:
    signals = t1_payload.get("portfolio_signals") or {}
    checklist = build_supplement_checklist(signals)
    coverage = build_t1_coverage(t1_payload)
    return {
        "envelope_version": ENVELOPE_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "qa_index": build_qa_index(),
        "system_prompt": compile_system_prompt(),
        "user_payload": {
            "t1": t1_payload,
            "profit": build_profit_context(t1_payload),
            "optional": build_optional_context(),
            "checklist": checklist,
            "jl4_catalog": build_jl4_catalog(signals),
        },
        "output_contract": build_output_contract(t1_payload, coverage, checklist),
        "coverage": coverage,
    }


def envelope_from_v1_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    up = raw.get("user_payload") or {}
    t1 = raw.get("t1_payload") or up.get("t1") or up.get("t1_payload") or raw
    if "batch_meta" not in t1 or "portfolio_signals" not in t1:
        raise ValueError(f"无法从 {path} 解析 t1_payload")
    return build_t2_preexec_envelope(t1)
