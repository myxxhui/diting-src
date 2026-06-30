"""Z0 段永平双闸编排 · 计算 / T2 增强 / BOM 落库 / 渲染注入。

[Ref: 32_ §2.4.9 · W1～W4 统一入口]
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.strategic import cvm_scorer
from apps.copilot.modules.strategic.duan_config import z0_cvm_gates


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _topology_snippet(stock_pool: dict[str, Any]) -> str:
    layers = stock_pool.get("ecosystem_topology") or stock_pool.get("topology") or []
    if not isinstance(layers, list):
        return ""
    parts = []
    for layer in layers[:6]:
        if isinstance(layer, dict):
            parts.append(f"{layer.get('label', '')}:{layer.get('role', '')}")
    return " | ".join(p for p in parts if p)


async def _load_sym_cvm(session: Optional[AsyncSession], symbols: set[str]) -> dict[str, dict]:
    if not session or not symbols:
        return {}
    from apps.copilot.db.models import CvmScorecard
    from sqlalchemy import select

    stmt = select(CvmScorecard).where(CvmScorecard.symbol.in_(list(symbols)))
    result = await session.execute(stmt)
    sym_cvm: dict[str, dict] = {}
    for row in result.scalars().all():
        if row.scores_json:
            sym_cvm[row.symbol] = row.scores_json
    return sym_cvm


def _score_stock_row(
    sym: str,
    st: dict[str, Any],
    node_duan: dict[str, Any],
    sym_cvm: dict[str, dict],
    enriched_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pos = st.get("ecosystem_position", "")
    role_tag, _ = cvm_scorer.infer_role_tag_from_position(pos)
    cvm_scores = sym_cvm.get(sym)
    pool_gate = None
    row = enriched_rows.get(sym)
    if row:
        cvm_scores = row.get("scores") or cvm_scores
        pool_gate = row.get("pool_gate")
    elif cvm_scores is None and role_tag:
        scored = cvm_scorer.score_symbol(sym, role_tag=role_tag)
        cvm_scores = scored.get("scores") or None
        pool_gate = scored.get("pool_gate")
        enriched_rows[sym] = scored
    return cvm_scorer.score_stock_duan_anchor(
        symbol=sym,
        node_duan=node_duan,
        ecosystem_position=pos,
        cvm_scores=cvm_scores,
        role_tag=role_tag,
        pool_gate=pool_gate,
    )


def compute_duan_dual_gates(
    stock_pool: dict[str, Any],
    *,
    sym_cvm: Optional[dict[str, dict]] = None,
    run_node_t2: bool = False,
    run_stock_t2: bool = False,
    sector_context: str = "",
    persist_to_pool: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """同步计算双闸；可选节点 T2 / 标的轻 T2 / 写回 bom_nodes。"""
    pool = copy.deepcopy(stock_pool)
    bom_nodes = pool.get("bom_nodes") or []
    if not bom_nodes:
        return {}, {}, pool

    sym_cvm = sym_cvm or {}
    topo = _topology_snippet(pool)
    sector = sector_context or pool.get("sector") or pool.get("genesis_sector") or ""

    if run_node_t2:
        from apps.copilot.metrics.node_segment_t2 import score_node_set_t2

        bom_nodes = score_node_set_t2(
            bom_nodes,
            sector_context=str(sector),
            topology_snippet=topo,
        )
        pool["bom_nodes"] = bom_nodes

    duan_node_scores: dict[str, dict] = {}
    stock_duan_scores: dict[str, dict] = {}
    enriched_rows: dict[str, dict[str, Any]] = {}

    for node in bom_nodes:
        nid = str(node.get("node_id", ""))
        tier = node.get("tier", "配套")
        layer = node.get("ecosystem_layer") or node.get("layer") or ""
        node_t2 = node.get("node_duan_t2") or node.get("node_t2")

        node_duan = cvm_scorer.score_node_segment_duan(
            node_id=nid,
            node_name=node.get("name", ""),
            tier=tier,
            ecosystem_layer=str(layer),
            node_t2=node_t2,
        )
        node_duan["evaluated_at"] = _utc_now_iso()
        if node_t2:
            node_duan["node_t2_ref"] = f"node_t2/{nid}.json"
        duan_node_scores[nid] = node_duan

        if persist_to_pool:
            node["node_duan_pack"] = node_duan
            if node_t2:
                node["node_duan_t2"] = node_t2

        node_stock_packs: list[tuple[str, dict, dict[str, Any]]] = []
        for st in node.get("stocks") or []:
            sym = st.get("symbol", "")
            if not sym:
                continue
            pack = _score_stock_row(sym, st, node_duan, sym_cvm, enriched_rows)
            key = f"{nid}:{sym}"
            stock_duan_scores[key] = pack
            node_stock_packs.append((key, pack, st))

        if run_stock_t2 and node_duan.get("verdict") in ("pass", "review"):
            _enrich_top_stocks_t2(node_stock_packs, enriched_rows, sym_cvm)

        for key, pack, st in node_stock_packs:
            sym = st.get("symbol", "")
            if sym and sym in enriched_rows:
                pack = _score_stock_row(sym, st, node_duan, sym_cvm, enriched_rows)
                stock_duan_scores[key] = pack
            if persist_to_pool:
                st["stock_duan_anchor"] = pack

    stock_duan_scores = cvm_scorer.apply_top2_anchor_cap(stock_duan_scores)
    if persist_to_pool:
        for node in bom_nodes:
            nid = str(node.get("node_id", ""))
            for st in node.get("stocks") or []:
                sym = st.get("symbol", "")
                key = f"{nid}:{sym}"
                if key in stock_duan_scores:
                    st["stock_duan_anchor"] = stock_duan_scores[key]

    pool["duan_dual_gate_evaluated_at"] = _utc_now_iso()
    return duan_node_scores, stock_duan_scores, pool


def _enrich_top_stocks_t2(
    node_stock_packs: list[tuple[str, dict, dict[str, Any]]],
    enriched_rows: dict[str, dict[str, Any]],
    sym_cvm: dict[str, dict],
) -> None:
    """W3 · 每节点 top2 候选跑 C2/C5 轻 T2。"""
    gates = z0_cvm_gates()
    cap = int(gates.get("max_green_anchors_per_node", 2))
    candidates = [
        (key, pack, st)
        for key, pack, st in node_stock_packs
        if pack.get("verdict") in ("anchor", "watch") and not pack.get("provisional")
    ]
    candidates.sort(
        key=lambda x: float(x[1].get("irreplaceability") or 0),
        reverse=True,
    )
    top = candidates[: max(cap * 2, cap)]
    if not top:
        return

    from apps.copilot.metrics.cvm_t2_semantic import score_peer_set_t2

    l1_rows = []
    for _key, _pack, st in top:
        sym = st.get("symbol", "")
        if sym in enriched_rows:
            l1_rows.append(enriched_rows[sym])
        else:
            pos = st.get("ecosystem_position", "")
            role_tag, _ = cvm_scorer.infer_role_tag_from_position(pos)
            if role_tag:
                row = cvm_scorer.score_symbol(sym, role_tag=role_tag)
                enriched_rows[sym] = row
                l1_rows.append(row)
    if not l1_rows:
        return
    try:
        t2_rows = score_peer_set_t2(l1_rows)
        for row in t2_rows:
            sym = row.get("symbol", "")
            if sym and row.get("scores"):
                sym_cvm[sym] = row["scores"]
                enriched_rows[sym] = row
    except Exception:
        pass


async def compute_duan_dual_gates_async(
    session: Optional[AsyncSession],
    stock_pool: dict[str, Any],
    *,
    run_node_t2: bool = False,
    run_stock_t2: bool = False,
    persist_to_pool: bool = False,
    sector_context: str = "",
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """异步入口 · 可选从 DB 加载 CVM。"""
    symbols: set[str] = set()
    for node in stock_pool.get("bom_nodes") or []:
        for st in node.get("stocks") or []:
            sym = st.get("symbol", "")
            if sym:
                symbols.add(sym)
    sym_cvm = await _load_sym_cvm(session, symbols)
    return compute_duan_dual_gates(
        stock_pool,
        sym_cvm=sym_cvm,
        run_node_t2=run_node_t2,
        run_stock_t2=run_stock_t2,
        sector_context=sector_context,
        persist_to_pool=persist_to_pool,
    )
