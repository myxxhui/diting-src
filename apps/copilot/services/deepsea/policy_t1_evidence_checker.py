"""Z0-M2 政策 T1 Phase C · 证据回检（防幻觉）。

检查 LLM 引用的原文句子是否真在政策原文中出现过。
遵循 22_ 事实交叉验证与防幻觉规约。

[Ref: 36_ §6.2 · 22_ 事实交叉验证与防幻觉规约]
"""
from __future__ import annotations

import re
from typing import Any


def normalize(text: str) -> str:
    """中文归一化：全角→半角、去除多余空白、统一引号。"""
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    # 全角字母数字转半角
    text = text.translate(str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ))
    # 全角标点转半角
    text = text.replace("，", ",").replace("。", ".").replace("；", ";")
    text = text.replace("：", ":").replace("？", "?").replace("！", "!")
    text = text.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")
    # 合并连续空白
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def check_evidence(
    quote: str,
    full_text: str,
    *,
    norm_chinese: bool = True,
) -> bool:
    """检查 LLM 引用的句子是否在原文中出现过。

    启动期采用归一化子串匹配（宽松模式）。
    扩展期可升级为语义相似度匹配（strict_mode=true）。

    Args:
        quote: LLM 输出的原文引用句子。
        full_text: 政策正文。
        norm_chinese: 是否做中文归一化。

    Returns:
        True 表示引用在原文中找到。
    """
    if not quote or not full_text:
        return False

    if norm_chinese:
        nq = normalize(quote)
        nt = normalize(full_text)
    else:
        nq = quote
        nt = full_text

    return nq in nt


def batch_check_evidence(
    sectors: list[dict[str, Any]],
    full_text: str,
    *,
    norm_chinese: bool = True,
) -> list[dict[str, Any]]:
    """批量回检一个 policy_sectors 列表中所有 evidence_quotes。

    返回带有 evidence_checked 标记的 sectors 列表。
    """
    results: list[dict[str, Any]] = []
    all_passed = True

    for sector in sectors:
        checked_quotes: list[str] = []
        sector_passed = True

        for quote in (sector.get("evidence_quotes") or []):
            if check_evidence(quote, full_text, norm_chinese=norm_chinese):
                checked_quotes.append(quote)
            else:
                sector_passed = False
                logger = __import__("logging").getLogger(__name__)
                logger.warning(
                    "证据回检未通过 sector=%s quote=%.60s",
                    sector.get("sector_name"), quote,
                )

        results.append({
            **sector,
            "evidence_quotes": checked_quotes,
            "evidence_checked": sector_passed,
        })
        if not sector_passed:
            all_passed = False

    return results, all_passed


__all__ = [
    "check_evidence",
    "batch_check_evidence",
    "normalize",
]
