"""Z0-M2 政策 T1 Dispatcher · B1 逐篇 LLM 评分 → B2 三因子衰减聚合 → C 准入。

无降级策略：LLM 不可用直接报 error，不用关键词规则冒充语义结果。

[Ref: 36_ §4/§5/§7 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

POLICY_PROBE_KEY = "M.policy.sector_direction"
S0_SCOPE = "S0"
SCOPE_DOC = "S0_doc"
T1_SOURCE = "llm:deepseek-chat"

# 落地力度多级加权系数（v5.1 · 替代 binary high_value_flag）
IMPLEMENTATION_FORCE_MULTIPLIER: dict[str, float] = {
    "comprehensive": 1.30,   # L4 多重配套：财政+税收+基金+审批 ≥3项
    "targeted":      1.20,   # L3 实质性扶持：≥1项实质性措施+量化目标
    "moderate":      1.10,   # L2 量化规划：有量化目标，无配套措施
    "light":         1.00,   # L1 方向性鼓励：鼓励/支持，无量化无配套（默认）
    "symbolic":      0.85,   # L0 仅提及：顺带提及/无针对性措施
}

IMPLEMENTATION_FORCE_LABELS: dict[str, str] = {
    "comprehensive": "多重配套", "targeted": "实质性扶持",
    "moderate": "量化规划", "light": "方向性鼓励", "symbolic": "仅提及",
}

_LLM_CFG = (
    Path(__file__).resolve().parents[4]
    / "data" / "config" / "metrics" / "z0_policy_t1_llm.yaml"
)


def _load_llm_config() -> dict[str, Any]:
    if not _LLM_CFG.is_file():
        return {}
    with _LLM_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _sync_db_url() -> str:
    import os

    raw = (os.environ.get("COPILOT_DB_URL") or "sqlite+aiosqlite:///./data/copilot.db").strip()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return raw


# ──────────────────────────────────────────────
# §7 成本预估算
# ──────────────────────────────────────────────

def estimate_cost(
    pending_docs: list[dict[str, Any]],
    *,
    model: str = "deepseek-chat",
    daily_yuan_budget: float = 5.0,
) -> dict[str, Any]:
    """处理前成本预估算。"""
    cfg = _load_llm_config()
    pricing = (cfg.get("cost_control") or {}).get("pricing") or {}
    p = pricing.get(model) or {"input_per_1M_yuan": 1.0, "output_per_1M_yuan": 2.0}

    total_input = 0
    for doc in pending_docs:
        text_len = (
            len(str(doc.get("title") or ""))
            + len(str(doc.get("summary") or ""))
            + len(str(doc.get("full_text") or ""))
        )
        est = int(text_len * 0.28)  # 中文字符→token
        total_input += min(est, 8500)  # 按截断后

    est_output = len(pending_docs) * 400
    cost = (total_input / 1_000_000 * p["input_per_1M_yuan"]
            + est_output / 1_000_000 * p["output_per_1M_yuan"])

    return {
        "total_docs": len(pending_docs),
        "est_input_tokens": total_input,
        "est_output_tokens": est_output,
        "est_cost_yuan": round(cost, 4),
        "model": model,
        "within_daily_budget": cost <= daily_yuan_budget,
    }


# ──────────────────────────────────────────────
# §5.1 实施状态推断
# ──────────────────────────────────────────────

def _load_impl_status_keywords() -> dict[str, list[str]]:
    from apps.copilot.services.deepsea.policy_reader import load_policy_keywords
    cfg = load_policy_keywords()
    return cfg.get("impl_status_keywords") or {}


def infer_impl_status(text: str) -> str:
    """从标题+正文推断政策实施状态。"""
    keywords = _load_impl_status_keywords()
    # 优先级：废止 > 征求意见 > 已完成 > 待执行 > 进行中 > 未知
    for status, kws in [
        ("废止_替代", keywords.get("废止_替代") or []),
        ("征求意见稿", keywords.get("征求意见稿") or []),
        ("已执行_完成", keywords.get("已执行_完成") or []),
        ("已发布_待执行", keywords.get("已发布_待执行") or []),
        ("已执行_进行中", keywords.get("已执行_进行中") or []),
    ]:
        if any(kw in text for kw in kws):
            return status
    return "状态未知"


# ──────────────────────────────────────────────
# §5.1 时间衰减计算
# ──────────────────────────────────────────────

def _load_time_decay_config() -> dict[str, Any]:
    cfg = _load_llm_config()
    return cfg.get("time_decay") or {}


def _load_source_authority() -> dict[str, float]:
    """读取数据源权威权重（按 source 域名 → 权重，合并 W_tier+W_source）。"""
    cfg = _load_llm_config()
    sa = cfg.get("source_authority") or {}
    if sa:
        return {k: float(v) for k, v in sa.items() if isinstance(v, (int, float))}
    # 回退到旧 doc_type_weights
    return cfg.get("doc_type_weights") or {}


def _load_impl_status_multipliers() -> dict[str, float]:
    cfg = _load_llm_config()
    return cfg.get("impl_status_multipliers") or {}


def compute_time_decay_weight(
    doc_type: str,
    days_since_published: int,
) -> float:
    """按文档类型计算时间衰减权重。"""
    decay_cfg = _load_time_decay_config()
    type_cfg = decay_cfg.get(doc_type, decay_cfg.get("L1", {}))
    fw = int(type_cfg.get("full_weight_days", 90))
    dtd = int(type_cfg.get("decay_to_days", 1095))
    mw = float(type_cfg.get("min_weight", 0.0))

    if days_since_published <= fw:
        return 1.0
    if days_since_published >= dtd:
        return mw
    # 线性衰减
    return round(1.0 - (days_since_published - fw) / (dtd - fw), 4)


def compute_composite_score(
    impact_score: float,
    source: str,
    impl_status: str,
    days_since_published: int,
) -> float:
    """三因子加权：impact × W_source × M_status × D_time。source 为域名如 gov.cn。"""
    sa = _load_source_authority()
    w_source = sa.get(source, sa.get("default", 0.6))
    m_status = _load_impl_status_multipliers().get(impl_status, 0.6)
    d_time = compute_time_decay_weight("L1", days_since_published)  # 时间衰减仍按旧分层（后续可改进）
    return round(impact_score * w_source * m_status * d_time, 4)


# ──────────────────────────────────────────────
# §3 Phase A · 数据读取
# ──────────────────────────────────────────────

def _fetch_pending_docs(
    conn: Any,
    *,
    limit: int,
    lookback_days: int,
) -> list[dict[str, Any]]:
    """读取待处理的政策文档（含全文）。"""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)
    rows = conn.execute(
        text(
            """
            SELECT d.doc_id, d.lineage_tags, d.published_at, d.object_uri
            FROM deepsea_doc_registry d
            LEFT JOIN deepsea_indicator_state s
              ON s.doc_id = d.doc_id AND s.probe_key = :probe_key
            WHERE d.doc_type = :doc_type
              AND s.id IS NULL
              AND (d.published_at IS NULL OR d.published_at >= :cutoff)
            ORDER BY COALESCE(d.published_at, d.created_at) DESC
            LIMIT :lim
            """
        ),
        {
            "probe_key": POLICY_PROBE_KEY,
            "doc_type": "policy",
            "cutoff": cutoff,
            "lim": limit,
        },
    ).mappings().all()

    out: list[dict[str, Any]] = []
    for row in rows:
        tags = row.get("lineage_tags") or {}
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = {}
        out.append({
            "doc_id": str(row["doc_id"]),
            "title": str(tags.get("title") or "")[:500],
            "summary": str(tags.get("summary") or tags.get("title") or "")[:2000],
            "full_text": str(tags.get("full_text") or ""),        # 新增：读取全文
            "source": str(tags.get("source") or ""),
            "feed_id": str(tags.get("feed_id") or ""),
            "feed_tier": str(tags.get("tier") or "L1"),            # 新增：读取 tier
            "published_at": row.get("published_at"),
            "object_uri": str(row.get("object_uri") or ""),
        })
    return out


# ──────────────────────────────────────────────
# §5 Phase B2 · 聚合 + 三因子衰减
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# v2.1: A股概念子概念匹配
# ──────────────────────────────────────────────
_CONCEPT_CACHE: dict[str, list[dict[str, str]]] = {}

def _reverse_lookup_canonical(raw_sector_name: str) -> str | None:
    """反向查找：给定 LLM 返回的原始术语，找到它属于哪个规范赛道（用于 canonical_sector 为空时）。"""
    sn = raw_sector_name.lower().strip()
    if not sn:
        return None
    from pathlib import Path
    import yaml as _yaml
    cfg_path = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
    try:
        with cfg_path.open(encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
        for cs_name, cs_data in (cfg.get("canonical_sectors") or {}).items():
            # 先检查 child_concepts 名称（模糊匹配：包含关系）
            for cc in cs_data.get("child_concepts") or []:
                ccn = str(cc["name"]).lower()
                if ccn and (ccn in sn or sn in ccn):
                    return cs_name
            # 再检查 llm_aliases
            for alias in cs_data.get("llm_aliases") or []:
                al = str(alias).lower()
                if al and (al in sn or sn in al):
                    return cs_name
            # 再检查 ingest_keywords
            for kw in cs_data.get("ingest_keywords") or []:
                kwl = str(kw).lower()
                if kwl and (kwl in sn or sn in kwl):
                    return cs_name
    except Exception:
        pass
    return None


def _load_display_name(canonical_sector: str) -> str:
    """从 YAML 读取赛道前端展示名（政策官方命名体系）。"""
    if canonical_sector.startswith("_unmapped:"):
        return canonical_sector.split(":", 1)[-1]
    try:
        from pathlib import Path
        import yaml as _yaml
        cfg_path = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
        with cfg_path.open(encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
        cs = (cfg.get("canonical_sectors") or {}).get(canonical_sector) or {}
        return str(cs.get("display_name") or canonical_sector)
    except Exception:
        return canonical_sector


def _load_child_concepts(canonical_sector: str) -> list[dict[str, str]]:
    """懒加载规范赛道 → A股概念板列表（仅 child_concepts，不含 ingest/llm_aliases）。
    
    v4.0: ingest_keywords 和 llm_aliases 仅用于文档→赛道映射（不纳入 concept 列表）。
    """
    if canonical_sector in _CONCEPT_CACHE:
        return _CONCEPT_CACHE[canonical_sector]
    from pathlib import Path
    import yaml as _yaml
    cfg_path = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
    concepts: list[dict[str, str]] = []
    try:
        with cfg_path.open(encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
        cs = (cfg.get("canonical_sectors") or {}).get(canonical_sector) or {}
        for cc in cs.get("child_concepts") or []:
            concepts.append({"concept_name": str(cc["name"]), "concept_code": str(cc.get("code", ""))})
    except Exception:
        pass
    # 去重
    seen = set()
    deduped = []
    for c in concepts:
        if c["concept_name"] not in seen:
            seen.add(c["concept_name"])
            deduped.append(c)
    _CONCEPT_CACHE[canonical_sector] = deduped
    return deduped


# ─── 同义词白名单（精确匹配之外允许的映射） ───
_CONCEPT_SYNONYM_WHITELIST: dict[str, list[str]] = {
    "人工智能": ["人工智能产业", "新一代人工智能", "大模型训练", "生成式人工智能"],
    "芯片概念": ["集成电路", "芯片产业", "半导体芯片", "先进计算"],
    "东数西算(算力)": ["算力基础设施", "智算中心", "算力网络", "算力枢纽"],
    "数据中心(AIDC)": ["数据中心", "智能计算中心", "AIDC"],
    "算力租赁": ["算力租赁", "算力服务"],
    "多模态AI": ["多模态大模型", "多模态"],
    "AI智能体": ["AI Agent", "智能体", "AI智能体"],
    "第三代半导体": ["碳化硅", "氮化镓", "SiC", "GaN", "第三代半导体"],
    "存储芯片": ["HBM", "高带宽存储", "存储芯片"],
    "MCU芯片": ["MCU", "微控制器", "车规级芯片"],
}

def _normalize_name(name: str) -> str:
    """去除空格、标点，统一小写。"""
    import re
    return re.sub(r"[\s\-\(\)（）]", "", name.lower())

def _exact_match_concept_name(concept_name: str, candidate_name: str) -> bool:
    """精确匹配：两端标准化后完全相等 → True。否则查同义词白名单。"""
    nn = _normalize_name(concept_name)
    cn = _normalize_name(candidate_name)
    if nn == cn:
        return True
    # 查白名单：candidate_name 是否在 concept_name 的允许同义词中
    synonyms = _CONCEPT_SYNONYM_WHITELIST.get(concept_name) or []
    for syn in synonyms:
        if _normalize_name(syn) == cn:
            return True
    # 双向查白名单
    for cname, slist in _CONCEPT_SYNONYM_WHITELIST.items():
        if _normalize_name(cname) == cn:
            for syn in slist:
                if _normalize_name(syn) == nn:
                    return True
    return False


def _match_child_concepts(canonical_sector: str, sector_name: str) -> list[dict[str, str]]:
    """将 LLM 输出的原文术语 sector_name 匹配到规范赛道下的 A股概念板名称列表。
    
    v4.0 变更（§5.5.3）：
    - 禁止子串匹配 → 仅精确匹配 + 同义词白名单
    - 未匹配到时不自动创建新概念（避免命名污染）
    - 仅返回 YAML 中配置的 child_concepts
    """
    candidates = _load_child_concepts(canonical_sector)
    matches: list[dict[str, str]] = []
    for c in candidates:
        if _exact_match_concept_name(c["concept_name"], sector_name):
            matches.append(c)
    # 未匹配到不自动创建新概念（v4.0 禁）
    if not matches:
        # 只保留与原文术语精确匹配或白名单匹配的
        return []
    return matches[:3]


def _reverse_lookup_concept_to_sector(concept_name: str) -> tuple[str | None, dict[str, str] | None]:
    """v5.0: 根据概念名反查其所属的规范赛道。
    
    从 YAML 的 canonical_sectors 反向遍历 child_concepts 找匹配。
    返回 (sector_key, concept_info_dict) 或 (None, None)。
    """
    try:
        cfg_path = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
        with cfg_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        for sector_key, sector_cfg in (cfg.get("canonical_sectors") or {}).items():
            for cc in sector_cfg.get("child_concepts") or []:
                if str(cc.get("name", "")).strip() == concept_name:
                    return sector_key, {
                        "concept_name": concept_name,
                        "concept_code": str(cc.get("code", "")),
                    }
    except Exception:
        pass
    return None, None


async def _llm_semantic_map_to_concept(
    term: str,
    canonical_sector: str,
    *,
    model: str = "deepseek-chat",
) -> str | None:
    """v5.0 语义映射兜底：将 LLM 自由术语映射到最近的 child_concept。
    
    仅作兜底用；新文档通过 T1 prompt 改造应不触发此路径。
    """
    concept_list = _load_child_concepts(canonical_sector)
    if not concept_list:
        return None
    options = ", ".join(c["concept_name"] for c in concept_list)
    prompt = f"""赛道「{canonical_sector}」下有这些A股概念板：
[{options}]

政策原文术语「{term}」最贴近其中哪个概念板？仅输出一个名字。如果都不贴近，输出 NONE。"""

    try:
        from apps.common.ai_dispatcher import AIDispatcher

        dispatcher = AIDispatcher.default()
        result = dispatcher.call(
            scene="z0_concept_semantic_map",
            messages=[
                {"role": "system", "content": "只输出概念名或 NONE，无其他内容。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=30,
            model_override=model,
            force_route="deepseek",
        )
        resp = str(result.text or "").strip()
        if resp.upper() == "NONE":
            return None
        # 验证输出是合法概念名
        valid_names = {c["concept_name"] for c in concept_list}
        if resp in valid_names:
            return resp
        # 模糊匹配一次
        for name in valid_names:
            if resp in name or name in resp:
                return name
        return None
    except Exception:
        return None


async def _verify_concept_relevance(
    concept_name: str,
    canonical_sector: str,
    policy_term: str,
    *,
    model: str = "deepseek-chat",
) -> bool:
    """v4.0 概念相关性校验闸：LLM 判断匹配是否合理。

    Returns True 仅当 LLM 回答 YES；超时/失败时默认保守处理为 False。
    """
    prompt = f"""你是A股行业分类专家。请判断以下匹配是否正确：

- 政策文档原文术语：「{policy_term}」
- 被匹配到的规范赛道：「{canonical_sector}」
- 被匹配到的A股概念板：「{concept_name}」

问题：这个A股概念板「{concept_name}」是否真正属于「{canonical_sector}」赛道，且与原文术语「{policy_term}」在A股投资逻辑上直接相关？

只回答一个词：YES 或 NO。如果原文术语是泛化/跨领域表述，或该概念与赛道核心定义无关，回答 NO。"""

    try:
        from apps.common.ai_dispatcher import AIDispatcher

        dispatcher = AIDispatcher.default()
        result = dispatcher.call(
            scene="z0_concept_verify",
            messages=[
                {"role": "system", "content": "只回答 YES 或 NO。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=10,
            model_override=model,
            force_route="deepseek",
        )
        resp_text = str(result.text or "").strip().upper()[:3]
        return "YES" in resp_text
    except Exception:
        return False


def _aggregate_with_decay(
    b1_results: list[dict[str, Any]],
    docs: list[dict[str, Any]],
    *,
    top_n: int = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """B2 三因子加权聚合。impl_status 使用 B1 LLM 推理结果（§5.0）。"""
    # doc_id → doc_meta
    doc_map: dict[str, dict[str, Any]] = {}
    for doc in docs:
        did = str(doc.get("doc_id") or "")
        if did:
            pub = doc.get("published_at")
            days = 0
            if pub:
                if isinstance(pub, datetime):
                    days = (datetime.now(timezone.utc).replace(tzinfo=None) - pub).days
                else:
                    days = 999

            doc_map[did] = {
                "source": str(doc.get("source") or "unknown"),
                "days_since_published": max(0, days),
                "title": str(doc.get("title") or ""),
            }

    sector_scores: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []

    for b1 in b1_results:
        did = str(b1.get("doc_id") or "")
        meta = doc_map.get(did, {})
        source = str(meta.get("source") or "unknown")
        days = int(meta.get("days_since_published") or 0)

        # impl_status 来自 B1 LLM 推理（§5.0）
        llm_meta = b1.get("doc_metadata") or {}
        impl_status = str(llm_meta.get("impl_status") or "状态未知")
        if impl_status not in ("已发布_待执行", "已执行_进行中", "已执行_完成",
                               "征求意见稿", "废止_替代", "状态未知"):
            impl_status = "状态未知"  # fallback 防御

        for item in b1.get("sectors") or []:
            sector = str(item.get("canonical_sector") or "").strip()
            raw_name = str(item.get("sector_name") or "").strip()
            if not sector or sector.lower() == "null":
                # 尝试逆向查找匹配规范赛道
                sector = _reverse_lookup_canonical(raw_name) or ""
            if not sector or sector.lower() == "null":
                # 仍然无法匹配：扔到 unmapped 桶
                if not raw_name:
                    continue
                sector = f"_unmapped:{raw_name}"
            # 子概念记录（用于二次排名）
            sub_name = str(item.get("sector_name") or "").strip()

            impact = float(item.get("impact_score") or 0)
            direction = str(item.get("direction") or "neutral")
            effective = compute_composite_score(impact, source, impl_status, days)
            w_total = (
                _load_source_authority().get(source, _load_source_authority().get("default", 0.6))
                * _load_impl_status_multipliers().get(impl_status, 0.6)
                * compute_time_decay_weight("L1", days)
            )

            bucket = sector_scores.setdefault(sector, {
                "sector": sector,
                "display_name": _load_display_name(sector),  # v4.0: 政策官方命名
                "composite_score": 0.0,
                "total_weight": 0.0,
                "doc_count": 0,
                "tailwind_count": 0,
                "headwind_count": 0,
                "tailwind_weight": 0.0,
                "headwind_weight": 0.0,
                "best_imp_strength": "symbolic",
                "sub_concepts": {},  # v2.0: 子概念证据收集
                # v3.0 Z0+: 新增字段累积
                "rev_type_votes": {},      # revenue_transmission_type 投票
                "narr_type_votes": {},      # narrative_catalyst_type 投票
                "phase_votes": {},          # policy_phase 投票
                "regime_change_count": 0,   # 政策拐点文档数
                "_published_dates": [],     # 聚合：收集发布时间用于加速度计算
            })
            bucket["composite_score"] += effective
            bucket["total_weight"] += w_total
            bucket["doc_count"] += 1
            if b1.get("high_value_flag"):
                bucket["high_value_flag"] = True

            # v5.0 A股概念板标记（优先级：LLM直出 selected_concepts > 规则匹配兜底）
            selected_concepts = b1.get("selected_concepts") or []
            _concept_by_sector = {}
            if selected_concepts and not sector.startswith("_unmapped:"):
                for concept_name in selected_concepts:
                    # 反查该概念属于哪个规范赛道
                    belonging_sector, concept_info = _reverse_lookup_concept_to_sector(concept_name)
                    if belonging_sector and concept_info:
                        _concept_by_sector.setdefault(belonging_sector, []).append(concept_info)
                # 将属于当前 sector 的概念归入 sub_concepts
                for cn_info in _concept_by_sector.get(sector, []):
                    sub = bucket["sub_concepts"].setdefault(cn_info["concept_name"], {
                        "sub_name": cn_info["concept_name"],
                        "concept_code": cn_info.get("concept_code", ""),
                        "doc_count": 0,
                        "composite_score": 0.0,
                        "total_weight": 0.0,
                        "evidence_quotes": [],
                    })
                    sub["doc_count"] += 1
                    sub["composite_score"] += effective
                    sub["total_weight"] += w_total
                    for quote in item.get("evidence_quotes") or []:
                        if len(sub["evidence_quotes"]) < 10:
                            sub["evidence_quotes"].append({
                                "quote": quote[:500],
                                "doc_id": did,
                                "direction": direction,
                                "impact_score": impact,
                            })
            elif not selected_concepts:
                # 兜底：v4.0 规则匹配（历史数据兼容）
                if not sector.startswith("_unmapped:"):
                    child_matches = _match_child_concepts(sector, sub_name)
                    for cm in child_matches:
                        sub = bucket["sub_concepts"].setdefault(cm["concept_name"], {
                            "sub_name": cm["concept_name"],
                            "concept_code": cm.get("concept_code", ""),
                            "doc_count": 0,
                            "composite_score": 0.0,
                            "total_weight": 0.0,
                            "evidence_quotes": [],
                        })
                        sub["doc_count"] += 1

            # v3.0 Z0+: 收集新字段
            rev_type = str(item.get("revenue_transmission_type") or "political_rhetoric")
            bucket["rev_type_votes"][rev_type] = bucket["rev_type_votes"].get(rev_type, 0) + 1

            narr_type = str(item.get("narrative_catalyst_type") or "political_slogan")
            bucket["narr_type_votes"][narr_type] = bucket["narr_type_votes"].get(narr_type, 0) + 1

            phase = str(item.get("policy_phase") or "maturation")
            bucket["phase_votes"][phase] = bucket["phase_votes"].get(phase, 0) + 1

            if item.get("policy_regime_change_flag"):
                bucket["regime_change_count"] = bucket.get("regime_change_count", 0) + 1

            # 收集发布时间（用于政策加速度）
            if days > 0:
                bucket["_published_dates"].append(
                    datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
                )

            # 落地力度：取多篇文档中的最强级别（comprehensive > targeted > moderate > light > symbolic）
            imp_str = str(item.get("implementation_strength") or "symbolic")
            _imp_order = {"comprehensive": 5, "targeted": 4, "moderate": 3, "light": 2, "symbolic": 1}
            if _imp_order.get(imp_str, 0) > _imp_order.get(bucket["best_imp_strength"], 0):
                bucket["best_imp_strength"] = imp_str

            # 累积实施工具包评分（按总权重归一化）
            toolkit = item.get("implementation_toolkit") or {}
            if isinstance(toolkit, dict) and toolkit:
                if "acc_toolkit" not in bucket:
                    bucket["acc_toolkit"] = {k: 0.0 for k in ["fiscal_support", "talent_programs", "land_infra", "regulatory_fast_track", "standards_legislation", "quantitative_targets"]}
                    bucket["toolkit_count"] = 0
                for k in bucket["acc_toolkit"]:
                    bucket["acc_toolkit"][k] += float(toolkit.get(k, 0))
                bucket["toolkit_count"] += 1

            if direction in ("strong_tailwind", "weak_tailwind"):
                bucket["tailwind_count"] += 1
                bucket["tailwind_weight"] += w_total
            elif direction in ("strong_headwind", "weak_headwind"):
                bucket["headwind_count"] += 1
                bucket["headwind_weight"] += w_total

            for quote in item.get("evidence_quotes") or []:
                evidence.append({
                    "sector": sector,
                    "doc_id": did,
                    "quote": quote[:300],
                    "direction": direction,
                })

    # 计算政策加速度（近30天 vs 前60天的文档密度比）
    _now = datetime.now(timezone.utc).replace(tzinfo=None)
    _cutoff_30 = _now - timedelta(days=30)
    _cutoff_90 = _now - timedelta(days=90)

    # 计算最终综合评分
    ranked: list[dict[str, Any]] = []
    for sector, bucket in sector_scores.items():
        tw = bucket["total_weight"]
        composite = round(bucket["composite_score"] / tw, 2) if tw > 0 else 0.0

        # 政策加速度计算
        dates = bucket.get("_published_dates") or []
        if dates:
            recent_30 = sum(1 for d in dates if d >= _cutoff_30)
            prior_60 = sum(1 for d in dates if _cutoff_90 <= d < _cutoff_30)
            acceleration = (recent_30 / max(prior_60, 1)) if prior_60 > 0 else (1.5 if recent_30 > 0 else 0.5)
        else:
            acceleration = 1.0

        # 主导类型提取（取票数最多的类型）
        def _dominant(votes: dict[str, int], default: str) -> str:
            if not votes:
                return default
            return max(votes, key=votes.get)

        dominant_rev = _dominant(bucket.get("rev_type_votes", {}), "political_rhetoric")
        dominant_narr = _dominant(bucket.get("narr_type_votes", {}), "political_slogan")
        dominant_phase = _dominant(bucket.get("phase_votes", {}), "maturation")
        regime_change_cnt = bucket.get("regime_change_count", 0)

        # 方向共识（加权投票）
        total_senti_w = bucket["tailwind_weight"] + bucket["headwind_weight"]
        if total_senti_w > 0:
            tw_ratio = bucket["tailwind_weight"] / total_senti_w
            hw_ratio = bucket["headwind_weight"] / total_senti_w
            if tw_ratio >= 0.8:
                consensus = "strong_tailwind"
            elif tw_ratio >= 0.6:
                consensus = "tailwind"
            elif hw_ratio >= 0.8:
                consensus = "strong_headwind"
            elif hw_ratio >= 0.6:
                consensus = "headwind"
            else:
                consensus = "mixed"
        else:
            consensus = "neutral"

        ranked.append({
            "sector": sector,
            "sector_type": "unmapped" if sector.startswith("_unmapped:") else "canonical",
            "composite_score": composite,
            "consensus_direction": consensus,
            "doc_count": bucket["doc_count"],
            "tailwind_count": bucket["tailwind_count"],
            "headwind_count": bucket["headwind_count"],
            "high_value_flag": bucket.get("high_value_flag", False),
            "imp_force_multiplier": IMPLEMENTATION_FORCE_MULTIPLIER.get(bucket.get("best_imp_strength", "light"), 1.0),
            "imp_force_label": IMPLEMENTATION_FORCE_LABELS.get(bucket.get("best_imp_strength", "light"), "方向性鼓励"),
            "best_imp_strength": bucket.get("best_imp_strength", "light"),
            "avg_toolkit": {
                k: round(v / max(bucket.get("toolkit_count", 1), 1), 1)
                for k, v in (bucket.get("acc_toolkit") or {}).items()
            } if bucket.get("acc_toolkit") else {},
            # v2.1: 子概念排名（按 A股概念板块归集 + 证据原文引用）
            "sub_concepts": sorted(
                [
                    {
                        "sub_name": sc["sub_name"],
                        "concept_code": sc.get("concept_code", ""),
                        "doc_count": sc["doc_count"],
                        "avg_composite": round(sc["composite_score"] / sc["total_weight"], 2) if sc["total_weight"] > 0 else 0.0,
                        "evidence_quotes": sc.get("evidence_quotes", [])[:5],
                    }
                    for sc in bucket.get("sub_concepts", {}).values()
                ],
                key=lambda x: x["doc_count"],
                reverse=True,
            )[:10],
            # v3.0 Z0+: 投资级评分字段
            "dominant_revenue_model": dominant_rev,
            "dominant_narrative_type": dominant_narr,
            "dominant_policy_phase": dominant_phase,
            "regime_change_doc_count": regime_change_cnt,
            "policy_acceleration": round(acceleration, 2),
        })

    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    return ranked[:top_n], evidence[:30]


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def _deduplicate_b1_sectors(sectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一文档内按 sector 去重，保留 score 最高的那条。"""
    seen: dict[str, dict[str, Any]] = {}
    for s in sectors:
        name = s.get("sector_name", "")
        if name in seen:
            if s.get("impact_score", 0) > seen[name].get("impact_score", 0):
                seen[name] = s
        else:
            seen[name] = s
    return list(seen.values())


def dispatch_policy_t1(
    *,
    limit: int = 200,
    lookback_days: int = 730,
    write_aggregate: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """T1 主入口：Phase A → B1(LLM) → B2(聚合衰减) → C(准入)。

    无降级策略：LLM 不可用或成本超预算直接报 error。
    """
    cfg = _load_llm_config()
    model = model or (cfg.get("llm_config") or {}).get("default_model", "deepseek-chat")
    daily_budget = float(
        (cfg.get("cost_control") or {}).get("daily_yuan_budget", 5.0)
    )

    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.begin() as conn:
            # Phase A：读取待处理文档
            pending = _fetch_pending_docs(conn, limit=limit, lookback_days=lookback_days)
            if not pending:
                return {
                    "status": "ok",
                    "detail": "无待处理的政策文档",
                    "processed": 0,
                    "source": T1_SOURCE,
                }

            # §7 成本预估算
            cost_est = estimate_cost(pending, model=model, daily_yuan_budget=daily_budget)
            if not cost_est["within_daily_budget"]:
                return {
                    "status": "error",
                    "detail": (
                        f"成本预估算超日预算：预估 ¥{cost_est['est_cost_yuan']} "
                        f"> 日预算 ¥{daily_budget}（{cost_est['total_docs']}篇 · "
                        f"~{cost_est['est_input_tokens']} input tokens）"
                    ),
                    "processed": 0,
                    "cost_estimate": cost_est,
                    "source": T1_SOURCE,
                }

            logger.info(
                "T1 成本预估算：%d 篇 · ~%d tokens · 预估 ¥%.4f · 预算内=%s",
                cost_est["total_docs"], cost_est["est_input_tokens"],
                cost_est["est_cost_yuan"], cost_est["within_daily_budget"],
            )

        # Phase B1：逐篇 LLM 评分（在连接外执行，不阻塞连接池）
        import asyncio

        from apps.copilot.services.deepsea.policy_t1_llm_scorer import dispatch_b1

        b1_successes, b1_errors = asyncio.run(dispatch_b1(pending, model=model))

        if not b1_successes:
            return {
                "status": "error",
                "detail": f"B1 LLM 评分全部失败（{len(b1_errors)}篇）",
                "processed": 0,
                "b1_errors": len(b1_errors),
                "errors": b1_errors[:5],
                "cost_estimate": cost_est,
                "source": T1_SOURCE,
            }

        if b1_errors:
            logger.warning("B1 部分失败：%d/%d 篇失败", len(b1_errors), len(pending))

        # Phase C：证据回检 + 去重
        from apps.copilot.services.deepsea.policy_t1_evidence_checker import (
            batch_check_evidence,
        )

        doc_map = {d["doc_id"]: d for d in pending}
        c_successes: list[dict[str, Any]] = []
        for b1 in b1_successes:
            did = b1.get("doc_id", "")
            doc = doc_map.get(did, {})
            ft = str(doc.get("full_text") or "")
            checked_sectors, all_passed = batch_check_evidence(b1.get("sectors") or [], ft)
            deduped = _deduplicate_b1_sectors(checked_sectors)
            c_successes.append({
                **b1,
                "sectors": deduped,
                "evidence_check_passed": all_passed,
            })

        # 写 DB（在连接内执行）
        processed = 0
        doc_snapshots: list[dict[str, Any]] = []
        with engine.begin() as conn:
            for sig in c_successes:
                did = sig.get("doc_id", "")
                inserted = _insert_policy_indicator_state(
                    conn, doc_id=did, signal=sig,
                )
                if inserted:
                    processed += 1
                    if sig.get("sectors"):
                        doc_snapshots.append(sig)

        # B2 聚合 + 写 S0 聚合
        aggregate: dict[str, Any] | None = None
        if write_aggregate and doc_snapshots:
            top_sectors, evidence = _aggregate_with_decay(
                doc_snapshots, pending, top_n=15,
            )
            if top_sectors:
                upsert_policy_indicator_state(
                    top_sectors=top_sectors,
                    evidence=evidence,
                    doc_id=None,
                    scope=S0_SCOPE,
                )
                aggregate = {"top_sectors": len(top_sectors), "scope": S0_SCOPE}

        return {
            "status": "ok" if processed > 0 else ("error" if b1_errors else "ok"),
            "detail": None if processed > 0 else "无新增政策文档",
            "processed": processed,
            "b1_errors": len(b1_errors) if b1_errors else None,
            "errors": b1_errors[:5] if b1_errors else None,
            "cost_estimate": cost_est,
            "aggregate": aggregate,
            "source": T1_SOURCE,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("政策 T1 dispatch 失败: %s", exc)
        return {
            "status": "error",
            "detail": f"T1 处理失败: {str(exc)[:300]}",
            "processed": 0,
            "source": T1_SOURCE,
        }
    finally:
        engine.dispose()


# ──────────────────────────────────────────────
#  DB 操作
# ──────────────────────────────────────────────

def _insert_policy_indicator_state(
    conn: Any,
    *,
    doc_id: str,
    signal: dict[str, Any],
) -> bool:
    """幂等写入 single-doc indicator_state。"""
    existing = conn.execute(
        text(
            "SELECT id FROM deepsea_indicator_state "
            "WHERE probe_key = :probe_key AND doc_id = :doc_id LIMIT 1"
        ),
        {"probe_key": POLICY_PROBE_KEY, "doc_id": doc_id},
    ).first()
    if existing:
        return False

    sectors = signal.get("sectors") or []
    direction = "neutral"
    if sectors:
        # 取 impact_score 最高的赛道方向
        top = max(sectors, key=lambda s: float(s.get("impact_score") or 0))
        direction = str(top.get("direction") or "neutral")

    evidence_quote = ""
    if sectors:
        for s in sectors:
            quotes = s.get("evidence_quotes") or []
            if quotes:
                evidence_quote = str(quotes[0])[:512]
                break

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    doc_meta = signal.get("doc_metadata") or {}
    snapshot = {
        "doc_id": doc_id,
        "title": signal.get("doc_id", ""),
        "policy_sectors": sectors,
        "overall_assessment": signal.get("overall_assessment", ""),
        "high_value_flag": signal.get("high_value_flag", False),
        "selected_concepts": signal.get("selected_concepts", []),  # v5.0
        "t1_source": signal.get("t1_source", T1_SOURCE),
        "llm_confidence": signal.get("llm_confidence", 0.0),
        "token_used": signal.get("token_used", 0),
        "evidence_check_passed": signal.get("evidence_check_passed", False),
        "impl_status": doc_meta.get("impl_status", "状态未知"),
        "impl_status_reasoning": doc_meta.get("impl_status_reasoning", ""),
    }

    conn.execute(
        text(
            """
            INSERT INTO deepsea_indicator_state (
                probe_key, symbol, scope, signal_status, evidence_quote,
                momentum_delta, snapshot, doc_id, inferred_at
            ) VALUES (
                :probe_key, NULL, :scope, :signal_status, :evidence_quote,
                :momentum_delta, :snapshot, :doc_id, :inferred_at
            )
            """
        ),
        {
            "probe_key": POLICY_PROBE_KEY,
            "scope": SCOPE_DOC,
            "signal_status": direction,
            "evidence_quote": evidence_quote,
            "momentum_delta": direction,
            "snapshot": json.dumps(snapshot, ensure_ascii=False),
            "doc_id": doc_id,
            "inferred_at": now,
        },
    )
    return True


def _delete_aggregate_state(scope: str = S0_SCOPE) -> None:
    engine = create_engine(_sync_db_url(), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM deepsea_indicator_state "
                    "WHERE probe_key = :probe_key AND scope = :scope"
                ),
                {"probe_key": POLICY_PROBE_KEY, "scope": scope},
            )
    finally:
        engine.dispose()


def upsert_policy_indicator_state(
    *,
    top_sectors: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
    doc_id: str | None = None,
    scope: str = S0_SCOPE,
) -> None:
    """T1 聚合落库（覆盖同 scope 旧聚合行）。"""
    import uuid

    _delete_aggregate_state(scope=scope)
    engine = create_engine(_sync_db_url(), future=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snapshot = {"top_sectors": top_sectors, "evidence": evidence or []}
    primary_direction = "neutral"
    if top_sectors:
        primary_direction = str(top_sectors[0].get("consensus_direction") or "neutral")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO deepsea_indicator_state (
                        probe_key, symbol, scope, signal_status, evidence_quote,
                        momentum_delta, snapshot, doc_id, inferred_at
                    ) VALUES (
                        :probe_key, NULL, :scope, :signal_status, :evidence_quote,
                        :momentum_delta, :snapshot, :doc_id, :inferred_at
                    )
                    """
                ),
                {
                    "probe_key": POLICY_PROBE_KEY,
                    "scope": scope,
                    "signal_status": primary_direction,
                    "evidence_quote": (evidence or [{}])[0].get("quote", "")[:512]
                    if evidence else "",
                    "momentum_delta": primary_direction,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                    "doc_id": doc_id or str(uuid.uuid4()),
                    "inferred_at": now,
                },
            )
    finally:
        engine.dispose()


__all__ = [
    "T1_SOURCE",
    "dispatch_policy_t1",
    "estimate_cost",
    "compute_time_decay_weight",
    "compute_composite_score",
    "infer_impl_status",
]
