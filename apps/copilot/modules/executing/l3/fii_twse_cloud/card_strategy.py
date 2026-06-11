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

FII_COL_HELP_TOTAL = """
<p><strong>合并营收</strong>指母公司<strong>鸿海精密（2317.TW）</strong>依 TWSE 月营收公告披露的<strong>合并报表总营收</strong>（新台币 · 亿元），涵盖云端网路、消费智能、电脑终端、元件及其他等全部产品线。</p>
<p class="mt-1.5">这是集团合并口径，<strong>不是</strong>单独「云端网路分部」披露值；工业富联（601138）为 A 股上市主体，本指标用于在 A 股季报空窗期读取母公司高频月报。</p>
"""

FII_COL_HELP_MOM = """
<p><strong>MoM（Month-over-Month）</strong> = <strong>月环比</strong>，公式 (本月 − 上月) / 上月 × 100%。</p>
<p class="mt-1.5">每一行对比的是<strong>日历上紧邻的上一个月</strong>（如 2026-04 的 MoM 对比 2026-03），<strong>不是</strong> YoY 同比（对比去年同月）。</p>
<p class="mt-1.5">合并 MoM 由相邻两月营收重算；云端 MoM 为 Solver 推导下限的月环比（<strong>营收规模</strong>，非净利/毛利率）。</p>
"""

FII_COL_HELP_CLOUD = """
<p><strong>云端网路 · 推导下限</strong>：官方月报<strong>不披露</strong>分板块金额；本列由方程 Solver 从合并总营收 + 上季权重锚 + IR 文本约束倒推，<strong>不是审计级分部真值</strong>。</p>
<p class="mt-1.5"><strong>推导占比</strong> = 云端推导下限 ÷ 合并营收 × 100%，反映「算力流水在集团中的推断权重」，与季报分部占比可能不同。</p>
"""

FII_COL_HELP_SYNC = """
<p><strong>对照</strong>：合并 MoM 与云端推导 MoM 同向比较——</p>
<ul class="list-disc pl-4 mt-1 space-y-0.5">
  <li><strong>同向扩张</strong>：两者 MoM 均为正</li>
  <li><strong>云端更强</strong>：云端 MoM &gt; 合并 MoM（算力流水增速跑赢集团整体）</li>
  <li><strong>云端偏弱</strong>：云端 MoM 为正但低于合并（果链/other 拉动更大）</li>
  <li><strong>分化</strong>：一正一负或云端 MoM 为负</li>
</ul>
"""

# 工业富联 601138 · 鸿海系持股（来源：2025 年报 + 2025-12-31 前十大股东公告）
HONHAI_OWNERSHIP_AS_OF = "2025-12-31"
HONHAI_CHINA_GALAXY_STAKE_PCT = 36.73
HONHAI_CONCERT_PARTY_STAKE_PCT = 85.72

FII_OWNERSHIP_DETAIL_HTML = f"""
<div class="space-y-2.5 text-[11px] text-gray-700 leading-relaxed">
  <p><strong>一句话：</strong>工业富联（601138）是鸿海精密（2317）控股的 A 股子公司；鸿海系合计持股约 <strong>{HONHAI_CONCERT_PARTY_STAKE_PCT}%</strong>，说了算。</p>
  <ul class="list-disc pl-4 space-y-1.5">
    <li><strong>第一大股东 · 中坚企业</strong>：直接持有 <strong>{HONHAI_CHINA_GALAXY_STAKE_PCT}%</strong>。中坚企业 100% 归鸿海精密所有（2025 年报「释义」）。</li>
    <li><strong>鸿海系合计</strong>：中坚 + 富泰华 + Ambit + 富士康科技集团等<strong>同一控制下</strong>股东，前十大口径约 <strong>{HONHAI_CONCERT_PARTY_STAKE_PCT}%</strong>（截至 {HONHAI_OWNERSHIP_AS_OF}）。</li>
    <li><strong>能分多少利润？</strong>工业富联<strong>现金分红</strong>按股比分配 → 鸿海系大约拿 <strong>{HONHAI_CONCERT_PARTY_STAKE_PCT:.0f}% 的分红</strong>，其余约 {100 - HONHAI_CONCERT_PARTY_STAKE_PCT:.0f}% 给其他股东。不是「赚 100 分 100」，公司会留一部分利润再投资（2025 年约把一半多净利润分出去）。</li>
    <li><strong>和本卡片的关系</strong>：这里读的是<strong>母公司鸿海合并月报</strong>（2317），不是 601138 单独财报；用来在 A 股季报空窗期看集团算力流水。</li>
  </ul>
  <p class="text-gray-500 pt-1 border-t border-gray-200">自行核对：工业富联 2025 年报「释义」+「前十大股东」；上交所 / 巨潮搜 601138。</p>
</div>
"""


def build_honhai_ownership_summary() -> dict[str, Any]:
    """卡面展示用 · 鸿海系持股摘要（与 executing_profiles/601138.yaml 同步）。"""
    return {
        "as_of": HONHAI_OWNERSHIP_AS_OF,
        "concert_party_pct": HONHAI_CONCERT_PARTY_STAKE_PCT,
        "concert_party_label": f"{HONHAI_CONCERT_PARTY_STAKE_PCT:.2f}%",
        "china_galaxy_pct": HONHAI_CHINA_GALAXY_STAKE_PCT,
        "china_galaxy_label": f"{HONHAI_CHINA_GALAXY_STAKE_PCT:.2f}%",
        "minority_pct_label": f"{100 - HONHAI_CONCERT_PARTY_STAKE_PCT:.2f}%",
        "detail_html": FII_OWNERSHIP_DETAIL_HTML.strip(),
    }


def fii_table_freshness_note_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    latest = str(rows[-1].get("period") or "")
    return (
        f'<p class="text-[10px] text-gray-500 leading-relaxed">'
        f"TWSE 月营收通常于<strong>次月上旬</strong>公告（较 A 股季报提前 1～2 个月）。"
        f"当前序列最新 <strong>{latest}</strong>。"
        f"<strong>6 月合并月报在 6 月 10 日通常尚未披露</strong>（鸿海/TWSE 惯例为<strong>次月 5～10 日</strong>发布上月营收），"
        f"故表内无 2026-06 行属正常；待 7 月上旬公告后 Cron 自动补齐。"
        f"若 TWSE OpenAPI 滞后于 FinMind，采集会自动以 FinMind 较新月份作为主档。"
        f'补采：<code class="text-[10px] bg-gray-100 px-0.5 rounded">l3-fii-twse-monthly</code> 或执行区「立即跑今日体检」。'
        f"</p>"
    )


def _mom_pct(cur: int | float, prev: int | float | None) -> float | None:
    if prev is None or prev <= 0:
        return None
    return (float(cur) - float(prev)) / float(prev) * 100.0


def _sorted_history(revenue_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(revenue_history or [], key=lambda h: (int(h["year"]), int(h["month"])))


def _honhai_monthly_series(revenue_history: list[dict[str, Any]], *, tail: int = 6) -> list[dict[str, Any]]:
    hist = _sorted_history(revenue_history)
    rows: list[dict[str, Any]] = []
    prev_rev: int | None = None
    for h in hist[-tail:]:
        y, m = int(h["year"]), int(h["month"])
        rev = int(h.get("total_revenue_ntd") or 0)
        mom = _mom_pct(rev, prev_rev)
        if mom is None and h.get("total_mom_pct") is not None:
            mom = float(h["total_mom_pct"])
        rows.append(
            {
                "period": f"{y}-{m:02d}",
                "total_billion_ntd": round(rev / 1e9, 1),
                "mom_pct": round(float(mom), 2) if mom is not None else None,
            }
        )
        prev_rev = rev
    return rows


def _sync_label(total_mom: float | None, cloud_mom: float | None) -> str:
    if total_mom is None or cloud_mom is None:
        return "—"
    if total_mom > 0 and cloud_mom > 0:
        if cloud_mom > total_mom + 0.5:
            return "云端更强"
        if cloud_mom + 0.5 < total_mom:
            return "云端偏弱"
        return "同向扩张"
    if total_mom <= 0 and cloud_mom <= 0:
        return "同向收缩"
    return "分化"


def _solver_cloud_lo_for_month(
    h: dict[str, Any],
    prev_h: dict[str, Any] | None,
    *,
    weights: dict[str, float],
    seasonality: dict[str, Any],
    pr_text: str = "",
) -> int:
    from apps.copilot.modules.executing.l3.fii_twse_cloud.t1_solver import solve_cloud_revenue_range

    total = int(h["total_revenue_ntd"])
    prev_total = int(prev_h["total_revenue_ntd"]) if prev_h else total
    mom = _mom_pct(total, prev_total) or float(h.get("total_mom_pct") or 0)
    t0 = {
        "report_year": int(h["year"]),
        "report_month": int(h["month"]),
        "total_revenue_ntd": total,
        "prev_month_revenue_ntd": prev_total,
        "total_mom_pct": mom,
        "total_yoy_pct": 0.0,
        "pr_raw_text": pr_text,
        "segment_baseline_weights_last_q": weights,
        "seasonality_factor_consumer": seasonality,
    }
    solved = solve_cloud_revenue_range(t0)
    return int(solved["cloud_revenue_ntd"]["lo"])


def build_cloud_vs_total_series(
    t0_payload: dict[str, Any],
    t1_contract: dict[str, Any],
    *,
    cloud_lo_history: list[dict[str, Any]] | None = None,
    tail: int = 5,
) -> list[dict[str, Any]]:
    """近 N 月 · 合并 MoM vs 云端网路推导 MoM 对照（营收规模，非利润）。"""
    hist = _sorted_history(t0_payload.get("revenue_history") or [])
    if len(hist) < 2:
        return []
    window = hist[-tail:]
    weights = t0_payload.get("segment_baseline_weights_last_q") or {}
    seasonality = t0_payload.get("seasonality_factor_consumer") or {}
    pr_text = str(t0_payload.get("pr_raw_text") or "")
    cur_y = int(t0_payload.get("report_year") or 0)
    cur_m = int(t0_payload.get("report_month") or 0)
    cur_lo = int((t1_contract.get("cloud_revenue_ntd") or {}).get("lo") or 0)

    lo_map = {
        (int(h["year"]), int(h["month"])): int(h["cloud_revenue_lower_ntd"])
        for h in (cloud_lo_history or [])
    }
    if cur_lo and cur_y and cur_m:
        lo_map[(cur_y, cur_m)] = cur_lo

    rows: list[dict[str, Any]] = []
    prev_total: int | None = None
    prev_lo: int | None = None
    full_idx = { (int(h["year"]), int(h["month"])): h for h in hist }

    for h in window:
        y, m = int(h["year"]), int(h["month"])
        total = int(h["total_revenue_ntd"])
        total_mom = _mom_pct(total, prev_total)

        key = (y, m)
        if key in lo_map:
            cloud_lo = lo_map[key]
        elif key == (cur_y, cur_m) and cur_lo:
            cloud_lo = cur_lo
        else:
            py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
            prev_h = full_idx.get((py, pm))
            use_pr = pr_text if (y, m) == (cur_y, cur_m) else ""
            cloud_lo = _solver_cloud_lo_for_month(
                h, prev_h, weights=weights, seasonality=seasonality, pr_text=use_pr
            )

        cloud_mom = _mom_pct(cloud_lo, prev_lo)
        share_pct = (cloud_lo / total * 100.0) if total > 0 else None
        rows.append(
            {
                "period": f"{y}-{m:02d}",
                "total_billion_ntd": round(total / 1e9, 1),
                "total_mom_pct": round(total_mom, 2) if total_mom is not None else None,
                "cloud_lo_billion_ntd": round(cloud_lo / 1e9, 1),
                "cloud_mom_pct": round(cloud_mom, 2) if cloud_mom is not None else None,
                "cloud_share_pct": round(share_pct, 1) if share_pct is not None else None,
                "sync_label": _sync_label(total_mom, cloud_mom),
            }
        )
        prev_total = total
        prev_lo = cloud_lo
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

    if moms and moms[-1] is not None and moms[-1] <= _ATTACK_LO_MOM_PCT:
        reasons.append(f"云端 MoM {moms[-1]:+.1f}% · 未达进攻线 {_ATTACK_LO_MOM_PCT:.0f}%")
    if len(moms) >= 2 and not (
        moms[-1] > _ATTACK_LO_MOM_PCT and moms[-2] > _ATTACK_LO_MOM_PCT
    ):
        m2 = moms[-2] if len(moms) >= 2 else None
        m1 = moms[-1]
        reasons.append(
            f"近两月云端 MoM {m2:+.1f}% → {m1:+.1f}% · 进攻需连续两月 >{_ATTACK_LO_MOM_PCT:.0f}%"
            if m2 is not None and m1 is not None
            else "云端 MoM 序列不足两月 · 待次月确认"
        )
    if rank == 1:
        reasons.append("IR 四板块 MoM 排名第 1 · 排名条件已满足")
    elif rank == 2:
        reasons.append("云端 MoM 排名第二 · 进攻需排名第 1")

    return {
        "status": "yellow",
        "label": "观察区",
        "summary": "云端增速未达连续两月 >15% 进攻线 · 发令维持观察",
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
    cloud_vs_total = build_cloud_vs_total_series(
        t0_payload, t1_contract, cloud_lo_history=history, tail=5
    )

    return {
        "panel_title": "三目标实战面板 · 601138 影子定价锚",
        "goal1_time_lag": {
            "title": "目标一 · 时间差套利",
            "subtitle": "母公司鸿海 2317 · 合并月营收 MoM（TWSE 月报 · 较 A 股季报提前 1～2 月）",
            "monthly_series": honhai_series,
        },
        "goal1b_cloud_vs_total": {
            "title": "云端网路 · 近五月环比对照",
            "subtitle": "合并总营收 MoM vs 云端推导 MoM · 看算力流水是否跑赢集团整体（营收规模 · 非净利）",
            "comparison_series": cloud_vs_total,
        },
        "honhai_ownership": build_honhai_ownership_summary(),
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


def t0_payload_from_node(node: dict[str, Any]) -> dict[str, Any]:
    """从已落库 node 还原 T0 载荷 · 供渲染期重算 card_strategy。"""
    rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
    t1 = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else {}
    macro = t1.get("macro") or {}
    return {
        "report_year": rm.get("report_year"),
        "report_month": rm.get("report_month"),
        "total_revenue_ntd": rm.get("total_revenue_ntd") or macro.get("total_ntd"),
        "total_mom_pct": rm.get("total_mom_pct") if rm.get("total_mom_pct") is not None else macro.get("mom_pct"),
        "total_yoy_pct": rm.get("total_yoy_pct") if rm.get("total_yoy_pct") is not None else macro.get("yoy_pct"),
        "pr_raw_text": rm.get("pr_raw_text") or "",
        "revenue_history": list(rm.get("revenue_history") or []),
        "segment_baseline_weights_last_q": dict(rm.get("segment_baseline_weights_last_q") or {}),
        "seasonality_factor_consumer": dict(rm.get("seasonality_factor_consumer") or {}),
    }


def refresh_card_strategy_for_node(
    node: dict[str, Any],
    *,
    cloud_lo_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """渲染/探针装配时重算 card_strategy（兼容旧快照缺 goal1b）。"""
    rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
    existing = rm.get("card_strategy") if isinstance(rm.get("card_strategy"), dict) else {}
    cmp = (existing.get("goal1b_cloud_vs_total") or {}).get("comparison_series") or []
    if len(cmp) >= 2:
        return existing
    t0 = t0_payload_from_node(node)
    rh = t0.get("revenue_history") or []
    if len(rh) < 2:
        ms = (existing.get("goal1_time_lag") or {}).get("monthly_series") or []
        if ms:
            rebuilt: list[dict[str, Any]] = []
            for r in ms:
                period = str(r.get("period") or "")
                if "-" not in period:
                    continue
                y_s, m_s = period.split("-", 1)
                try:
                    y, m = int(y_s), int(m_s)
                    rev_b = float(r.get("total_billion_ntd") or 0)
                except (TypeError, ValueError):
                    continue
                rebuilt.append(
                    {
                        "year": y,
                        "month": m,
                        "total_revenue_ntd": int(rev_b * 1e9),
                        "total_mom_pct": r.get("mom_pct"),
                    }
                )
            if len(rebuilt) >= 2:
                t0["revenue_history"] = rebuilt
    if len(t0.get("revenue_history") or []) < 2:
        return existing
    t1 = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else {}
    if not t1:
        from apps.copilot.modules.executing.l3.fii_twse_cloud.t1_contract import build_t1_contract

        t1 = build_t1_contract(t0)
    return build_card_strategy(t0, t1, cloud_lo_history=cloud_lo_history)
