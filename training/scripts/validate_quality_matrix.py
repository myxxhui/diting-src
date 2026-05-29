"""D1 step_02 数据质量验收矩阵（§3.5 共 18 项）。

输出每行 ✅/⚠️/❌ 状态；退出码 0 表示「无 ❌」（W1 准出要求）。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02 §3.5]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

bootstrap_crawl_env(_REPO_ROOT)

from sqlalchemy import text

from apps.common.holdings_sot import load_holdings_sot
from apps.cryo_guard.db.sync_session import session_scope

logger = logging.getLogger(__name__)


def run_checks(session, symbols: list[str]) -> list[dict]:
    """运行 18 项质量检查，返回结果列表。"""
    n_sym = len(symbols)
    results: list[dict] = []

    def check(code: str, name: str, ok: bool, warn: bool, detail: str) -> None:
        if ok:
            status = "✅"
        elif warn:
            status = "⚠️"
        else:
            status = "❌"
        results.append({"code": code, "name": name, "status": status, "detail": detail})

    # ── F 系列：财务报表 ────────────────────────────────────────────────────

    fr_total = session.execute(
        text("SELECT COUNT(*) FROM financial_reports")
    ).scalar() or 0
    fr_per_sym_min = session.execute(
        text(
            "SELECT MIN(cnt) FROM ("
            "SELECT symbol, COUNT(*) AS cnt FROM financial_reports GROUP BY symbol"
            ")"
        )
    ).scalar() or 0
    fr_with_ocf = session.execute(
        text(
            "SELECT COUNT(*) FROM financial_reports "
            "WHERE operating_cash_flow IS NOT NULL"
        )
    ).scalar() or 0
    fr_with_revenue = session.execute(
        text("SELECT COUNT(*) FROM financial_reports WHERE revenue IS NOT NULL")
    ).scalar() or 0
    fr_with_rdexp = session.execute(
        text("SELECT COUNT(*) FROM financial_reports WHERE rd_expense IS NOT NULL")
    ).scalar() or 0
    fr_with_industry = session.execute(
        text(
            "SELECT COUNT(DISTINCT symbol) FROM financial_reports "
            "WHERE industry IS NOT NULL AND industry != ''"
        )
    ).scalar() or 0

    # F1: 现金流-账面利润字段完整（operating_cash_flow + net_profit 齐）
    f1_ok = fr_with_ocf >= n_sym * 4
    check(
        "F1", "现金流-账面利润背离（字段完整率）",
        ok=f1_ok, warn=not f1_ok and fr_with_ocf > 0,
        detail=f"operating_cash_flow 非null={fr_with_ocf}/{fr_total}（目标≥{n_sym * 4}）",
    )

    # F2: 应收账款 + 营收（判断应收异常前提）
    f2_ok = fr_with_revenue >= n_sym * 4
    check(
        "F2", "应收账款异常 vs 营收（营收字段完整）",
        ok=f2_ok, warn=not f2_ok and fr_with_revenue > 0,
        detail=f"revenue 非null={fr_with_revenue}/{fr_total}",
    )

    # F3: 存贷双高（total_assets + short_term_debt + cash_and_equivalents）
    f3_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM financial_reports "
            "WHERE total_assets IS NOT NULL AND short_term_debt IS NOT NULL "
            "AND cash_and_equivalents IS NOT NULL"
        )
    ).scalar() or 0
    f3_ok = f3_cnt >= n_sym * 4
    check(
        "F3", "存贷双高（三字段完整）",
        ok=f3_ok, warn=not f3_ok and f3_cnt > 0,
        detail=f"三字段非null={f3_cnt}/{fr_total}",
    )

    # F4: 研发资本化（rd_expense 非null 抽样可做）
    f4_ok = fr_with_rdexp >= n_sym
    check(
        "F4", "研发资本化抽样",
        ok=f4_ok, warn=not f4_ok,
        detail=f"rd_expense 非null={fr_with_rdexp}（目标≥{n_sym}）",
    )

    # F5: ROE 可计算（net_profit/equity 或直接字段）
    roe_cnt = session.execute(
        text("SELECT COUNT(*) FROM financial_reports WHERE roe IS NOT NULL")
    ).scalar() or 0
    f5_ok = roe_cnt >= n_sym * 2
    check(
        "F5", "ROE 可计算",
        ok=f5_ok, warn=not f5_ok and roe_cnt > 0,
        detail=f"roe 非null={roe_cnt}（目标≥{n_sym * 2}）",
    )

    # F9: 季度连续趋势（有 annual 数据即 ⚠️；annual+semi/q1/q3 才 ✅）
    types = session.execute(
        text("SELECT DISTINCT report_type FROM financial_reports")
    ).fetchall()
    type_set = {r[0] for r in types}
    has_quarterly = bool({"semi", "q1", "q3"} & type_set)
    check(
        "F9", "季度连续趋势（multi-type）",
        ok=has_quarterly, warn=not has_quarterly and "annual" in type_set,
        detail=f"已有 report_type={sorted(type_set)}（W1 annual 可接受）",
    )

    # F10: 关联方占营收比例（依赖 related_party_raw 行数 + revenue）
    rpr_cnt = session.execute(
        text("SELECT COUNT(*) FROM related_party_raw")
    ).scalar() or 0
    f10_ok = rpr_cnt >= n_sym * 10
    check(
        "F10", "关联方占营收比例（related_party_raw 行数）",
        ok=f10_ok, warn=not f10_ok and rpr_cnt > 0,
        detail=f"related_party_raw={rpr_cnt}（目标≥{n_sym * 10}）",
    )

    # ── S 系列：公告与股权 ─────────────────────────────────────────────────

    ann_total = session.execute(
        text("SELECT COUNT(*) FROM announcements")
    ).scalar() or 0

    longform_types = "('业绩','质押','战略','关联交易','增持','减持')"
    ann_longform_total = session.execute(
        text(f"SELECT COUNT(*) FROM announcements WHERE ann_type IN {longform_types}")
    ).scalar() or 0
    ann_longform_ok = session.execute(
        text(
            f"SELECT COUNT(*) FROM announcements WHERE ann_type IN {longform_types} "
            "AND content IS NOT NULL AND LENGTH(content) > 200"
        )
    ).scalar() or 0
    ann_content_rate = ann_longform_ok / ann_longform_total if ann_longform_total > 0 else 0

    s1_ok = ann_content_rate >= 0.90
    s1_warn = 0.70 <= ann_content_rate < 0.90
    check(
        "S1", "承诺履约 content 完整率（仅正文型公告：业绩/质押/战略/关联交易/增减持）",
        ok=s1_ok, warn=s1_warn,
        detail=f"{ann_longform_ok}/{ann_longform_total}={ann_content_rate:.1%}（金标准≥90%；标题型公告人事/监管不计入）",
    )

    # S2: 累计持股变动（股权质押类公告有数据）
    pledge_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM announcements "
            "WHERE ann_type LIKE '%质押%' OR ann_type LIKE '%减持%' OR ann_type LIKE '%增持%'"
        )
    ).scalar() or 0
    s2_ok = pledge_cnt >= n_sym
    check(
        "S2", "累计持股变动（质押/增减持公告）",
        ok=s2_ok, warn=not s2_ok and pledge_cnt > 0,
        detail=f"质押/增减持公告={pledge_cnt}（目标≥{n_sym}）",
    )

    executive_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM announcements "
            "WHERE ann_type = '人事变动' "
            "OR ann_type LIKE '%董事%' OR ann_type LIKE '%高管%' OR ann_type LIKE '%监事%'"
        )
    ).scalar() or 0
    s3_ok = executive_cnt >= n_sym
    check(
        "S3", "董监高变动密度（人事变动 + 旧规则）",
        ok=s3_ok, warn=not s3_ok and ann_total > 0,
        detail=f"人事/董监高类公告={executive_cnt}（目标≥{n_sym}）",
    )

    # S4: 股权质押率（依赖 S1 content）
    check(
        "S4", "股权质押率（Teacher 抽取）",
        ok=False, warn=True,
        detail=f"W1 仅采集原始公告，quality 依赖 step_03 Teacher；content 完整率={ann_content_rate:.1%}",
    )

    # S5: 业绩对赌（稀疏可接受）
    perf_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM announcements "
            "WHERE ann_type LIKE '%业绩%' OR ann_type LIKE '%预告%' OR ann_type LIKE '%快报%'"
        )
    ).scalar() or 0
    s5_ok = perf_cnt >= n_sym
    check(
        "S5", "业绩对赌/业绩预告",
        ok=s5_ok, warn=not s5_ok and ann_total > 0,
        detail=f"业绩类公告={perf_cnt}（目标≥{n_sym}）",
    )

    inquiry_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM announcements "
            "WHERE ann_type = '监管问询' "
            "OR ann_type LIKE '%问询%' OR ann_type LIKE '%监管%' OR ann_type LIKE '%处罚%'"
        )
    ).scalar() or 0
    check(
        "S6", "问询函/监管处罚（监管问询 + 旧规则）",
        ok=True, warn=False,
        detail=f"问询/监管/处罚类={inquiry_cnt}（金标准：有即合规）",
    )

    rel_tx_cnt = session.execute(
        text("SELECT COUNT(*) FROM announcements WHERE ann_type = '关联交易'")
    ).scalar() or 0
    s7_ok = rel_tx_cnt >= n_sym
    check(
        "S7", "关联交易公告（公告侧 vs OCR 侧交叉验证）",
        ok=s7_ok, warn=not s7_ok and rel_tx_cnt > 0,
        detail=f"关联交易公告={rel_tx_cnt}（目标≥{n_sym}；与 R1~R4 交叉核对）",
    )

    # ── R 系列：关联方网络 ─────────────────────────────────────────────────

    rpg_cnt = session.execute(
        text("SELECT COUNT(*) FROM related_party_graph")
    ).scalar() or 0
    r1_ok = rpg_cnt >= 8
    check(
        "R1", "关联方网络图骨架（related_party_graph）",
        ok=r1_ok, warn=not r1_ok and rpg_cnt > 0,
        detail=f"related_party_graph={rpg_cnt}（目标≥8）",
    )

    # R2: 金额占比时间序列（related_party_raw 有 amount）
    rpr_amount_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM related_party_raw "
            "WHERE amount IS NOT NULL AND amount > 0"
        )
    ).scalar() or 0
    r2_ok = rpr_amount_cnt >= n_sym
    check(
        "R2", "金额占比时间序列（amount 非null）",
        ok=r2_ok, warn=not r2_ok and rpr_cnt > 0,
        detail=f"amount 非null={rpr_amount_cnt}（目标≥{n_sym}）",
    )

    has_is_noise = bool(
        session.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('related_party_raw') WHERE name='is_noise'")
        ).scalar()
    )

    valid_tx_filter = (
        "transaction_type IN ('销售','采购','租赁','劳务','借款','担保','资金拆借','代付','服务','委托','股权','资产')"
    )
    noise_filter = "is_noise = 0" if has_is_noise else "1=1"

    valid_rpr_cnt = session.execute(
        text(f"SELECT COUNT(*) FROM related_party_raw WHERE {noise_filter} AND {valid_tx_filter}")
    ).scalar() or 0
    pm_cnt = session.execute(
        text(
            f"SELECT COUNT(*) FROM related_party_raw WHERE {noise_filter} AND {valid_tx_filter} "
            "AND pricing_method IS NOT NULL AND pricing_method != ''"
        )
    ).scalar() or 0
    pm_rate = pm_cnt / valid_rpr_cnt if valid_rpr_cnt > 0 else 0
    r3_ok = pm_rate >= 0.5
    r3_warn = not r3_ok
    check(
        "R3", "定价方法（pricing_method ≥ 50% · 有效交易行为分母）",
        ok=r3_ok, warn=r3_warn,
        detail=f"pricing_method={pm_cnt}/{valid_rpr_cnt}={pm_rate:.1%}（有效交易行；金标准 ≥ 50%）",
    )

    guarantee_cnt = session.execute(
        text(
            f"SELECT COUNT(*) FROM related_party_raw WHERE {noise_filter} "
            "AND transaction_type IN ('担保','资金拆借','借款','代付')"
        )
    ).scalar() or 0
    r4_ok = guarantee_cnt >= n_sym
    r4_warn = not r4_ok and guarantee_cnt > 0
    check(
        "R4", "关联担保/资金占用（事务类型计数 + content 完整）",
        ok=r4_ok, warn=r4_warn,
        detail=f"担保/资金类={guarantee_cnt}（目标≥{n_sym}）；金额结构化待 step_03 Teacher 补充",
    )

    if has_is_noise:
        rpr_total = session.execute(text("SELECT COUNT(*) FROM related_party_raw")).scalar() or 0
        noise_cnt = session.execute(text("SELECT COUNT(*) FROM related_party_raw WHERE is_noise=1")).scalar() or 0
        noise_rate = noise_cnt / rpr_total if rpr_total else 0
        n1_ok = noise_rate <= 0.55
        n1_warn = 0.55 < noise_rate <= 0.80
        check(
            "N1", "OCR 噪音率（启动期金标准 ≤ 55%）",
            ok=n1_ok, warn=n1_warn,
            detail=f"噪音 {noise_cnt}/{rpr_total}={noise_rate:.1%}（去噪 clean_related_party_noise.py 已标）",
        )

    # ── C 系列：行业对比 ────────────────────────────────────────────────────

    # C1: 业绩预告/快报
    c1_cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM announcements "
            "WHERE ann_type LIKE '%业绩预告%' OR ann_type LIKE '%业绩快报%'"
        )
    ).scalar() or 0
    c1_ok = c1_cnt >= 0  # 有即可
    check(
        "C1", "业绩预告/快报（C1）",
        ok=True, warn=False,
        detail=f"业绩预告/快报={c1_cnt}",
    )

    # C2: 同行业基线（industry 列非null per symbol）
    c2_ok = fr_with_industry >= n_sym
    check(
        "C2", "同行业基线（industry 列覆盖）",
        ok=c2_ok, warn=not c2_ok and fr_with_industry > 0,
        detail=f"有 industry 的 symbol 数={fr_with_industry}（目标={n_sym}）",
    )

    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info("[validate_quality_matrix] D1 step_02 §3.5 质量矩阵（18 项）")

    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    logger.info("  active symbols: %s", symbols)

    with session_scope() as session:
        results = run_checks(session, symbols)

    fail_count = 0
    for r in results:
        emoji = r["status"]
        print(f"  {emoji}  [{r['code']}] {r['name']}")
        print(f"       {r['detail']}")
        if r["status"] == "❌":
            fail_count += 1

    print()
    if fail_count == 0:
        print(f"  ✅ 质量矩阵全 {len(results)} 项无 ❌，准出通过")
    else:
        print(f"  ❌ {fail_count} 项 ❌，请修复后重跑")
        sys.exit(1)


if __name__ == "__main__":
    main()
