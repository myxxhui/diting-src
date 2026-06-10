"""T1 线性约束求解 · 云端板块营收区间。

[Ref: 28_ §2.2 fii_twse_cloud · 防置换方程]
"""
from __future__ import annotations

import re
from typing import Any

from apps.copilot.modules.executing.l3.fii_twse_cloud.constants import (
    HISTORICAL_TERM_DICTIONARY,
    OFFICIAL_SEGMENTS,
    SEGMENT_BASELINE_WEIGHTS_LAST_Q,
)

_SEGMENT_TOKEN_TO_KEY: tuple[tuple[str, str], ...] = (
    ("雲端網路", "cloud"),
    ("云端网路", "cloud"),
    ("云端网络", "cloud"),
    ("消費智能", "consumer"),
    ("消费智能", "consumer"),
    ("電腦終端", "computing"),
    ("电脑终端", "computing"),
    ("元件及其他", "components"),
)


def _segment_aliases() -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    for seg in OFFICIAL_SEGMENTS:
        out[seg["key"]] = list(seg["aliases"]) + [seg["zh"], seg["en"]]
    return {k: tuple(v) for k, v in out.items()}


def _token_to_key(token: str) -> str | None:
    for frag, key in _SEGMENT_TOKEN_TO_KEY:
        if frag in token:
            return key
    return None


def _is_ranking_line(line: str) -> bool:
    s = line.strip()
    if re.match(r"^(MoM|YoY)\s", s):
        return True
    return " > " in s and "類別" not in s and "类别" not in s and len(s) < 160


def parse_mom_ranking(text: str) -> list[str] | None:
    """解析 IR 汇总表「MoM 四大產品類別排序」行。"""
    m = re.search(r"MoM\s+([^\n]+)", text)
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"\s*>\s*", m.group(1)) if p.strip()]
    keys: list[str] = []
    for part in parts:
        key = _token_to_key(part)
        if key:
            keys.append(key)
    return keys or None


def _monthly_narrative_section(text: str, *, year: int, month: int) -> str:
    """截取当月 IR 叙述段（第 2 页「说明如下」~「前 N 月累计」）。"""
    # 优先：当月正文后的第一个「说明如下」块（排除累计段）
    intro = re.search(
        rf"{year}\s*{month}\s*月營收|{year}\s*年{month:02d}月營收|{year}\s*年{month}月營收",
        text,
    )
    search_from = intro.start() if intro else 0
    explain = re.search(r"說明如下\s*:?", text[search_from:])
    if explain:
        start = search_from + explain.end()
        rest = text[start:]
        stop = re.search(rf"{year}\s*年前\d+月累|前4月累計|前4月累计|第二季", rest)
        return rest[: stop.start()] if stop else rest[:2500]
    # 兜底：全文第一个说明块
    explain2 = re.search(r"說明如下\s*:?", text)
    if explain2:
        rest = text[explain2.end() :]
        stop = re.search(rf"{year}\s*年前\d+月累|前4月累計", rest)
        return rest[: stop.start()] if stop else rest[:2500]
    return text


def extract_segment_narratives(text: str, *, year: int, month: int) -> dict[str, str]:
    """第 2 页 numbered 叙述 · 每板块一条，不含 MoM/YoY 排序行。"""
    scoped = _monthly_narrative_section(text, year=year, month=month)
    aliases = _segment_aliases()
    narratives: dict[str, str] = {}
    for seg in OFFICIAL_SEGMENTS:
        key = seg["key"]
        for alias in seg["aliases"] + (seg["zh"],):
            pat = re.compile(
                rf"[（(]\d[）)]\s*[「『\"]?[^」』\"]*{re.escape(alias)}"
                rf"[^」』\"]*[」』\"]?[^。\n]*",
                re.S,
            )
            hits = [re.sub(r"\s+", " ", h.strip()) for h in pat.findall(scoped) if not _is_ranking_line(h)]
            if hits:
                narratives[key] = "。".join(hits)[:400]
                break
        if key in narratives:
            continue
        lines = [ln.strip() for ln in re.split(r"[\n。；;]", scoped) if ln.strip()]
        line_hits = [
            ln
            for ln in lines
            if any(a in ln for a in aliases[key])
            and not _is_ranking_line(ln)
            and re.search(r"類別|类别|方面|产品|產品", ln)
        ]
        if line_hits:
            narratives[key] = "。".join(line_hits)[:400]
    return narratives


def _segment_fuzzy_terms(text: str, *, year: int, month: int) -> dict[str, list[str]]:
    scoped = _monthly_narrative_section(text, year=year, month=month)
    out: dict[str, list[str]] = {s["key"]: [] for s in OFFICIAL_SEGMENTS}
    for seg in OFFICIAL_SEGMENTS:
        key = seg["key"]
        for alias in seg["aliases"] + (seg["zh"],):
            if alias not in scoped:
                continue
            for term in sorted(HISTORICAL_TERM_DICTIONARY, key=len, reverse=True):
                for m in re.finditer(re.escape(alias), scoped):
                    chunk = scoped[max(0, m.start() - 10) : m.start() + 100]
                    if _is_ranking_line(chunk):
                        continue
                    if term in chunk and term not in out[key]:
                        out[key].append(term)
    return {k: v for k, v in out.items() if v}


def _terms_in_text(text: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for term, bounds in sorted(HISTORICAL_TERM_DICTIONARY.items(), key=lambda x: -len(x[0])):
        if term in text and not any(term == t for t, _ in found):
            found.append((term, bounds))
    return found


def _mom_bounds_from_terms(terms: list[tuple[str, dict[str, Any]]]) -> tuple[float, float]:
    lo, hi = -100.0, 100.0
    for _, b in terms:
        if "mom_pct" in b:
            blo, bhi = b["mom_pct"]
            lo = max(lo, float(blo))
            hi = min(hi, float(bhi))
    if lo > hi:
        lo, hi = -5.0, 30.0
    return lo, hi


def _yoy_bounds_from_terms(terms: list[tuple[str, dict[str, Any]]]) -> tuple[float, float]:
    lo, hi = -100.0, 200.0
    for _, b in terms:
        if "yoy_pct" in b:
            blo, bhi = b["yoy_pct"]
            lo = max(lo, float(blo))
            hi = min(hi, float(bhi))
    if lo > hi:
        lo, hi = 0.0, 100.0
    return lo, hi


def _segment_meta(weights: dict[str, float]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for seg in OFFICIAL_SEGMENTS:
        key = seg["key"]
        meta[key] = {
            "zh": seg["zh"],
            "weight_pct": float(weights.get(key, SEGMENT_BASELINE_WEIGHTS_LAST_Q.get(key, 0))),
            "revenue_published": False,
        }
    return meta


def solve_cloud_revenue_range(t0: dict[str, Any]) -> dict[str, Any]:
    """已知总营收 + 权重 + 文本约束 → 云端绝对营收区间（NTD）。"""
    total = float(t0["total_revenue_ntd"])
    prev_total = float(
        t0.get("prev_month_revenue_ntd") or total / (1 + float(t0["total_mom_pct"]) / 100)
    )
    weights = t0.get("segment_baseline_weights_last_q") or SEGMENT_BASELINE_WEIGHTS_LAST_Q
    w_cloud = float(weights.get("cloud", 22.0)) / 100.0
    w_cons = float(weights.get("consumer", 47.0)) / 100.0
    w_comp = float(weights.get("computing", 8.0)) / 100.0
    w_compo = float(weights.get("components", 23.0)) / 100.0
    y, m = int(t0["report_year"]), int(t0["report_month"])

    pr_text = str(t0.get("pr_raw_text") or "")
    segment_narratives = extract_segment_narratives(pr_text, year=y, month=m)
    cloud_narrative = segment_narratives.get("cloud", "")
    seg_terms = _segment_fuzzy_terms(pr_text, year=y, month=m)
    cloud_terms_list = seg_terms.get("cloud") or []
    terms = _terms_in_text(" ".join(cloud_terms_list) + " " + cloud_narrative)
    mom_lo, mom_hi = _mom_bounds_from_terms(terms)
    yoy_lo, yoy_hi = _yoy_bounds_from_terms(terms)

    season = t0.get("seasonality_factor_consumer") or {}
    cons_range = season.get("consumer_mom_pct_range") or [-20.0, 40.0]
    cons_lo, cons_hi = float(cons_range[0]), float(cons_range[1])

    prev_cloud = prev_total * w_cloud
    prev_cons = prev_total * w_cons
    prev_comp = prev_total * w_comp
    prev_compo = prev_total * w_compo

    cloud_from_mom = (
        prev_cloud * (1 + mom_lo / 100.0),
        prev_cloud * (1 + mom_hi / 100.0),
    )
    weight_anchor = (total * w_cloud * 0.85, total * w_cloud * 1.25)

    cons_low = prev_cons * (1 + cons_lo / 100.0)
    cons_high = prev_cons * (1 + cons_hi / 100.0)
    comp_low = prev_comp * 0.85
    comp_high = prev_comp * 1.15
    compo_low = prev_compo * 0.85
    compo_high = prev_compo * 1.15

    def cloud_bounds_given_others(oc: float, cc: float, cp: float) -> tuple[float, float]:
        return (
            max(0.0, total - cc - cp - oc),
            max(0.0, total - cons_low - comp_low - compo_low),
        )

    lp_lo, lp_hi = cloud_bounds_given_others(cons_high, comp_high, compo_high)
    lp_lo2, lp_hi2 = cloud_bounds_given_others(cons_low, comp_low, compo_low)
    lower = max(cloud_from_mom[0], weight_anchor[0], lp_lo, lp_lo2)
    upper = min(cloud_from_mom[1], weight_anchor[1], lp_hi, lp_hi2)
    if lower > upper:
        mid = total * w_cloud
        lower, upper = mid * 0.9, mid * 1.1

    mom_ranking = parse_mom_ranking(pr_text)
    cloud_mom_rank: int | str = "unknown"
    if mom_ranking and "cloud" in mom_ranking:
        cloud_mom_rank = mom_ranking.index("cloud") + 1
    elif re.search(r"第一|居首|最高", cloud_narrative):
        cloud_mom_rank = 1

    if cloud_mom_rank == 1 and mom_lo < 5.0:
        mom_lo = 5.0

    has_narrative = bool(cloud_narrative and re.search(r"類別|类别|方面", cloud_narrative))
    ir_quality = "segment_narrative" if has_narrative else (
        "table_with_rank" if mom_ranking else "table_only_or_missing"
    )

    return {
        "cloud_revenue_ntd": {"lo": int(lower), "hi": int(upper)},
        "segments": _segment_meta(weights),
        "pr_evidence": {
            "mom_ranking": mom_ranking,
            "cloud_mom_rank": cloud_mom_rank,
            "segment_narratives": {k: v[:200] for k, v in segment_narratives.items()},
            "segment_fuzzy_terms": seg_terms,
            "fuzzy_terms": cloud_terms_list,
            "mom_bound_pct": [round(mom_lo, 1), round(mom_hi, 1)],
            "yoy_bound_pct": [round(yoy_lo, 1), round(yoy_hi, 1)],
            "ir_text_quality": ir_quality,
        },
        "solver": {
            "method": "linear_constraint",
            "note": "官方仅公布合并总营收；其余三板块未披露金额，由权重+季节性+文本约束方程消元",
        },
    }


# 兼容旧测试/调用
extract_segment_snippets = extract_segment_narratives
