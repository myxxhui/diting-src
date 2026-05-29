"""从 akshare 抓取行业分类，更新 financial_reports.industry 列。

策略（双重保障）：
  1. 优先调用 akshare stock_individual_info_em 获取真实行业
  2. akshare 不可用时，从 MY_HOLDINGS_YAML 的 segment 字段推断行业分类
     （segment → 证监会行业 映射表，见 SEGMENT_INDUSTRY_MAP）

配置：
  MY_HOLDINGS_YAML   — 持仓 SoT 路径（默认 data/config/my_holdings.yaml）
  CRYO_THROTTLE_SEC  — 每次请求间隔（默认 0.6s）

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02 §7.2]
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

bootstrap_crawl_env(_REPO_ROOT)

from sqlalchemy import text

from apps.common.holdings_sot import load_holdings_sot
from apps.cryo_guard.db.sync_session import session_scope

logger = logging.getLogger(__name__)

THROTTLE = float(os.environ.get("CRYO_THROTTLE_SEC", "0.6"))

# segment → 近似行业（证监会大类）；当 akshare 不可用时作为离线兜底
SEGMENT_INDUSTRY_MAP: dict[str, str] = {
    "电力基建2": "电力设备",
    "16T光模块与CPO": "通信设备",
    "散热革命": "专用设备",
    # 兜底
    "default": "其他",
}


def fetch_industry_akshare(symbol: str) -> str | None:
    """通过 akshare stock_individual_info_em 获取个股行业分类。"""
    try:
        import akshare as ak  # 懒导入，连不上时不报错
        df = ak.stock_individual_info_em(symbol=symbol)
        for label in ["行业", "所属行业", "证监会行业"]:
            rows = df[df.iloc[:, 0] == label]
            if not rows.empty:
                val = str(rows.iloc[0, 1]).strip()
                if val and val not in ("-", "nan", "None"):
                    return val
        return None
    except Exception as exc:
        logger.warning("⚠️  %s akshare 行业获取失败: %s", symbol, exc)
        return None


def fetch_industry_from_segment(sot, symbol: str) -> str | None:
    """从 holdings SoT 的 segment 字段推断行业（akshare 不可用时兜底）。"""
    try:
        import yaml  # noqa: PLC0415

        yaml_path = Path(os.environ.get("MY_HOLDINGS_YAML", "data/config/my_holdings.yaml"))
        if not yaml_path.is_file():
            return None
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for h in data.get("holdings", []):
            if str(h.get("symbol", "")).strip() == symbol:
                segment = str(h.get("segment", "")).strip()
                return SEGMENT_INDUSTRY_MAP.get(segment, SEGMENT_INDUSTRY_MAP["default"])
        return None
    except Exception as exc:
        logger.warning("⚠️  %s segment 兜底失败: %s", symbol, exc)
        return None


def update_industry(symbol: str, industry: str, session) -> int:
    """把 industry 值写入该 symbol 下所有财报行（仅更新空白行），返回更新行数。"""
    result = session.execute(
        text(
            "UPDATE financial_reports SET industry = :industry "
            "WHERE symbol = :symbol AND (industry IS NULL OR industry = '')"
        ),
        {"industry": industry, "symbol": symbol},
    )
    return result.rowcount


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    logger.info("[crawl_industry] 开始，共 %d 只: %s", len(symbols), symbols)

    updated_total = 0
    ok_count = 0
    fallback_count = 0
    skipped = 0

    with session_scope() as session:
        for symbol in symbols:
            # 1. 先尝试 akshare
            industry = fetch_industry_akshare(symbol)
            time.sleep(THROTTLE)
            source = "akshare"

            # 2. akshare 失败则 segment 兜底
            if not industry:
                industry = fetch_industry_from_segment(sot, symbol)
                source = "segment"

            if not industry:
                logger.warning("  ⚠️  %s 行业两级均未能获取，跳过", symbol)
                skipped += 1
                continue

            cnt = update_industry(symbol, industry, session)
            updated_total += cnt
            if source == "akshare":
                ok_count += 1
            else:
                fallback_count += 1
            logger.info(
                "  %s %s → %s（%s，更新 %d 行）",
                "✅" if source == "akshare" else "⚠️",
                symbol,
                industry,
                source,
                cnt,
            )

        session.commit()

    logger.info(
        "[crawl_industry] 完成：akshare=%d 只 / segment兜底=%d 只 / 跳过=%d 只；共更新 %d 行",
        ok_count,
        fallback_count,
        skipped,
        updated_total,
    )


if __name__ == "__main__":
    main()
