"""DeepSea 缓存组常量。

[Ref: 28_ §2.11.5 fii-cninfo-dynamic]
"""
from __future__ import annotations

FII_CNINFO_DYNAMIC = "fii-cninfo-dynamic"

# 同篇业绩会/公告全文一次 Cache · 并发概念探针
FII_CNINFO_DYNAMIC_PROBES: tuple[str, ...] = (
    "fii_gb200_milestone",
    "fii_odm_direct_ratio",
    "fii_liquid_attach",
    "fii_ai_margin",  # registry 键 · 别名 fii_ai_margin_tone
    "r_fii_gb200_flaw",
)

# 设计稿对外名称 · 与 probe_registry alias_probe_key 对齐
FII_CNINFO_DYNAMIC_PEER_ALIASES: dict[str, str] = {
    "fii_ai_margin": "fii_ai_margin_tone",
}
