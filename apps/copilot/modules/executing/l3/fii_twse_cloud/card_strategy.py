"""fii_twse_cloud 卡片战略层 · 三目标展示与发令枪信号。

[Ref: 28_ §2.2 fii_twse_cloud · 601138 影子定价锚]
"""
from __future__ import annotations

from typing import Any

_FLAT_TERMS = frozenset({"持平", "略为衰退", "略為衰退", "略减", "略減", "显著衰退", "顯著衰退"})
_ATTACK_LO_MOM_PCT = 15.0
_APPROACH_LO_MOM_PCT = 10.0

_HELP_HTML = """
<p><strong>fii_twse_cloud</strong> 是工业富联（601138）的「高频时间机器」与「影子定价锚」——
通过母公司鸿海（2317.TW）TWSE 月报 + IR 文本，在 A 股季报盲窗期提前 1～2 个月透视算力流水。</p>
<ul class="list-disc pl-4 space-y-1 mt-2">
  <li><strong>目标一 · 时间差套利</strong>：台股月报制（每年 12 次）vs A 股季报制（4 次），展示鸿海合并总营收 MoM 序列。</li>
  <li><strong>目标二 · 剥离果链噪音</strong>：方程 Solver 从混浊总营收中倒推「云端网路」绝对下限；消费智能以总营收 MoM 作季节性对照（非分部真值）。</li>
  <li><strong>目标三 · 程序化发令枪</strong>：
    🟢 连续两月云端推导下限 MoM &gt; 15% 且 MoM 排名 first → 右侧进攻；
    🔴 持平/衰退词或排名跌出前二 → 防守减仓；
    🟡 介于两者之间 → 观察。</li>
</ul>
"""


def _mom_pct(cur: int | float, prev: int | float | None) -> float | None:
    if prev is None or prev <= 0:
        return None
    return (float(cur) - float(prev)) / float(prev) * 100.0


def _honhai_monthly_series(revenue_history: list[dict[str, Any]], *, tail: int = 6) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for h in (revenue_history or [])[-tail:]:
        y, m = int(h["year"]), int(h["month"])
        mom = h.get("total_mom_pct")
        rev = int(h.get("total_revenue_ntd") or 0)
        rows.append(
            {
                "period": f"{y}-{m:02d}",
                "total_billion_ntd": round(rev / 1e9, 1),
                "mom_pct": round(float(mom), 2) if mom is not None else None,
            }
        )
    return rows


def _cloud_lo_mom_series(cloud_lo_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(cloud_lo_history, key=lambda x: (x.get("year", 0), x.get("month", 0)))
    out: list[dict[str, Any]] = []
    prev_lo: int | None = None
    for row in ordered:
        lo = int(row.get("cloud_revenue_lower_ntd") or 0)
        y, m = int(row.get("year", 0)), int(row.get("month", 0))
        mom = _mom_pct(lo, prev_lo)
        out.append(
            {
                "period": f"{y}-{m:02d}",
                "cloud_lo_billion_ntd": round(lo / 1e9, 1),
                "mom_pct": round(mom, 2) if mom is not None else None,
            }
        )
        prev_lo = lo
    return out


def compute_trend_signal(
    *,
    cloud_lo_mom_series: list[dict[str, Any]],
    cloud_mom_rank: int | str | None,
    cloud_terms: list[str] | None,
    consumer_terms: list[str] | None,
) -> dict[str, Any]:
    moms = [r["mom_pct"] for r in cloud_lo_mom_series if r.get("mom_pct") is not None]
    rank = cloud_mom_rank if isinstance(cloud_mom_rank, int) else None
    terms = list(cloud_terms or []) + list(consumer_terms or [])
    reasons: list[str] = []

    if len(moms) >= 2 and moms[-1] > _ATTACK_LO_MOM_PCT and moms[-2] > _ATTACK_LO_MOM_PCT and rank == 1:
        return {
            "status": "green",
            "label": "进攻发令",
            "summary": "连续两月云端推导下限 MoM > 15% 且板块 MoM 排名第一",
            "reasons": [
                f"云端下限 MoM：{moms[-2]:+.1f}% → {moms[-1]:+.1f}%",
                f"MoM 排名：第 {rank} 位",
            ],
        }

    flat_hit = [t for t in terms if t in _FLAT_TERMS]
    if flat_hit:
        reasons.append(f"IR 用词触发 flat：{'、'.join(flat_hit)}")
    if rank is not None and rank > 2:
        reasons.append(f"云端 MoM 排名跌至第 {rank} 位（阈值：前二）")

    if flat_hit or (rank is not None and rank > 2):
        return {
            "status": "red",
            "label": "防守预警",
            "summary": "提货放缓或果链噪音占主导 · 建议削减底层多头",
            "reasons": reasons or ["排名或 IR 定性触发防守条件"],
        }

    if rank == 2:
        reasons.append("云端 MoM 排名第二（未达 first 进攻条件）")
    if moms and moms[-1] >= _APPROACH_LO_MOM_PCT:
        reasons.append(f"云端下限 MoM {moms[-1]:+.1f}% 接近 15% 进攻阈值")
    if len(moms) == 1 and moms[0] > _ATTACK_LO_MOM_PCT:
        reasons.append("仅单月高增速 · 待次月确认")

    return {
        "status": "yellow",
        "label": "观察区",
        "summary": "未满足进攻/防守硬条件 · 持续跟踪次月月报",
        "reasons": reasons or ["信号中性"],
    }


def build_card_strategy(
    t0_payload: dict[str, Any],
    t1_contract: dict[str, Any],
    *,
    cloud_lo_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pr = t1_contract.get("pr_evidence") or {}
    seg_terms = pr.get("segment_fuzzy_terms") or {}
    history = list(cloud_lo_history or [])
    y = int(t0_payload.get("report_year") or 0)
    m = int(t0_payload.get("report_month") or 0)
    cur_lo = int((t1_contract.get("cloud_revenue_ntd") or {}).get("lo") or 0)

    if not any(h.get("year") == y and h.get("month") == m for h in history):
        history.append({"year": y, "month": m, "cloud_revenue_lower_ntd": cur_lo})

    honhai_series = _honhai_monthly_series(t0_payload.get("revenue_history") or [])
    cloud_series = _cloud_lo_mom_series(history)
    total_mom = float(t0_payload.get("total_mom_pct") or 0)
    cloud_terms = seg_terms.get("cloud") or []
    consumer_terms = seg_terms.get("consumer") or []

    trend = compute_trend_signal(
        cloud_lo_mom_series=cloud_series,
        cloud_mom_rank=pr.get("cloud_mom_rank"),
        cloud_terms=cloud_terms,
        consumer_terms=consumer_terms,
    )

    latest_cloud_mom = cloud_series[-1]["mom_pct"] if cloud_series else None

    return {
        "goal1_time_lag": {
            "title": "目标一 · 时间差套利",
            "subtitle": "母公司鸿海 2317 · 合并月营收 MoM（TWSE 月报 · 较 A 股季报提前 1～2 月）",
            "monthly_series": honhai_series,
        },
        "goal2_noise_isolation": {
            "title": "目标二 · 剥离果链噪音",
            "subtitle": "Solver 倒推云端绝对下限 vs 消费智能季节性对照",
            "cloud_lo_billion": round(cur_lo / 1e9, 1),
            "cloud_lo_mom_pct": latest_cloud_mom,
            "cloud_lo_series": cloud_series[-3:],
            "cloud_ir_terms": cloud_terms,
            "consumer_mom_proxy_pct": round(total_mom, 2),
            "consumer_mom_note": "总营收 MoM 代理（含果链 · 非消费分部真值）",
            "consumer_ir_terms": consumer_terms,
        },
        "goal3_trend_trigger": {
            "title": "目标三 · 程序化发令枪",
            **trend,
        },
        "help_html": _HELP_HTML.strip(),
    }


def help_html() -> str:
    return _HELP_HTML.strip()
