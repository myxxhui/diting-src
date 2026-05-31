"""维度一 · 时间线合理性评估（T0 纯规则 · 不调 LLM）。

[Ref: step_15 §3.1]
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from apps.copilot.modules.roadmap.calendar import trading_days_between

FLAG_ADVISORY: dict[str, str] = {
    "build_window_tight": "建仓时间不足，建议提前或减小目标仓位",
    "window_overlap": "爆发窗重叠，注意资金/精力分配",
    "capital_collision": "重叠期目标仓位合计超 100%，需取舍",
    "sequence_inversion": "排序与时间倒挂，建议重排",
}


def _parse_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    s = str(val)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _windows_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def evaluate_timeline_feasibility(
    nodes: list[dict[str, Any]],
    *,
    build_lead_days: int = 15,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """对每条 timeline 节点计算 feasibility_flags + advisories（纯函数）。"""
    today = today or date.today()
    enriched: list[dict[str, Any]] = []
    for n in nodes:
        flags: list[str] = []
        advisories: list[str] = []
        anchor = _parse_date(n.get("anchor_date"))
        w_start = _parse_date(n.get("window_start")) or anchor
        w_end = _parse_date(n.get("window_end")) or anchor
        if anchor and w_start and w_end:
            lead = n.get("build_lead_days", build_lead_days)
            td = trading_days_between(today, anchor)
            if td < int(lead):
                flags.append("build_window_tight")
                advisories.append(
                    f"{n.get('symbol') or n.get('title', '')}: "
                    f"距爆发点仅 {td} 交易日 < 门槛 {lead} · {FLAG_ADVISORY['build_window_tight']}"
                )
        enriched.append(
            {
                **n,
                "feasibility_flags": flags,
                "advisories": advisories,
                "window_start": w_start.isoformat() if w_start else n.get("window_start"),
                "window_end": w_end.isoformat() if w_end else n.get("window_end"),
                "_w_start": w_start,
                "_w_end": w_end,
                "_anchor": anchor,
            }
        )

    # 按 symbol 去重：每只 symbol 只保留最有代表性的节点参与 overlap/capital 比较。
    # 代表性规则：anchor_date 最早；相同时 target_weight_pct 最大。
    # 无 symbol 的节点（sym 为空字符串）单独保留，各自参与比较。
    _repr_idx: dict[str, int] = {}  # sym -> 代表节点在 enriched 中的索引
    _no_sym_indices: list[int] = []  # 无 symbol 的节点索引，始终参与比较
    for _idx, _n in enumerate(enriched):
        _sym = _n.get("symbol") or _n.get("title", "")
        if not _sym:
            _no_sym_indices.append(_idx)
            continue
        if _sym not in _repr_idx:
            _repr_idx[_sym] = _idx
        else:
            _existing = enriched[_repr_idx[_sym]]
            _n_anchor = _n.get("_anchor")
            _e_anchor = _existing.get("_anchor")
            if _n_anchor and _e_anchor:
                if _n_anchor < _e_anchor:
                    _repr_idx[_sym] = _idx
                elif _n_anchor == _e_anchor:
                    # anchor 相同则保留 target_weight_pct 更大的
                    _n_w = float(_n.get("target_weight_pct") or 0)
                    _e_w = float(_existing.get("target_weight_pct") or 0)
                    if _n_w > _e_w:
                        _repr_idx[_sym] = _idx
            elif _n_anchor and not _e_anchor:
                _repr_idx[_sym] = _idx
    # 代表节点集合：有 symbol 的取代表 + 无 symbol 的全部保留
    _repr_set: set[int] = set(_repr_idx.values()) | set(_no_sym_indices)

    # 两两比较 overlap / capital（仅在代表节点之间 && 不同 symbol 之间进行）
    for i, a in enumerate(enriched):
        flags = list(a.get("feasibility_flags") or [])
        advisories = list(a.get("advisories") or [])
        a_sym = a.get("symbol") or a.get("title", "")
        a_start, a_end = a.get("_w_start"), a.get("_w_end")
        if not a_start or not a_end:
            a["feasibility_flags"] = flags
            a["advisories"] = advisories
            continue
        if i not in _repr_set:
            # 非代表节点不参与 overlap/capital 比较，不背假 flag
            continue
        for j, b in enumerate(enriched):
            if i >= j:
                continue
            if j not in _repr_set:
                continue
            b_sym = b.get("symbol") or b.get("title", "")
            if a_sym == b_sym:
                # 同 symbol 跳过，防止脏数据导致标的自咬
                continue
            b_start, b_end = b.get("_w_start"), b.get("_w_end")
            if not b_start or not b_end:
                continue
            if _windows_overlap(a_start, a_end, b_start, b_end):
                for idx in (i, j):
                    fl = enriched[idx].setdefault("feasibility_flags", [])
                    if "window_overlap" not in fl:
                        fl.append("window_overlap")
                    adv = enriched[idx].setdefault("advisories", [])
                    adv.append(
                        f"{a_sym} 与 {b_sym} 爆发窗重叠 · {FLAG_ADVISORY['window_overlap']}"
                    )
                w_a = float(a.get("target_weight_pct") or 0)
                w_b = float(b.get("target_weight_pct") or 0)
                if w_a + w_b > 100:
                    for idx in (i, j):
                        fl = enriched[idx].setdefault("feasibility_flags", [])
                        if "capital_collision" not in fl:
                            fl.append("capital_collision")
                        adv = enriched[idx].setdefault("advisories", [])
                        adv.append(
                            f"重叠期仓位合计 {w_a + w_b:.0f}% · {FLAG_ADVISORY['capital_collision']}"
                        )

    # sequence inversion
    seq_pairs = [
        (n.get("sequence_no"), n.get("_anchor"), n.get("symbol") or n.get("title"))
        for n in enriched
        if n.get("sequence_no") is not None and n.get("_anchor")
    ]
    if len(seq_pairs) >= 2:
        sorted_by_seq = sorted(seq_pairs, key=lambda x: x[0])
        sorted_by_date = sorted(seq_pairs, key=lambda x: x[1])
        if [s[0] for s in sorted_by_seq] != [s[0] for s in sorted_by_date]:
            for n in enriched:
                fl = n.setdefault("feasibility_flags", [])
                if "sequence_inversion" not in fl:
                    fl.append("sequence_inversion")
                adv = n.setdefault("advisories", [])
                adv.append(FLAG_ADVISORY["sequence_inversion"])

    out: list[dict[str, Any]] = []
    for n in enriched:
        out.append(
            {
                **{k: v for k, v in n.items() if not k.startswith("_")},
                "feasibility_flags": n.get("feasibility_flags") or [],
                "advisories": n.get("advisories") or [],
            }
        )
    return out
