"""The Sniffer — 主题嗅探。

输入：批量原文 + 时间窗口
输出：候选题材簇（cluster_id / keyword / freq_growth / confidence）

路由：
  - remote（Opus）：嗅探 prompt 推理 → JSON
  - mock：本地 TF-IDF 简化，用于 CI 与无 key 环境

[Ref: 03_/02_维度二/.../step_02 §3.5.4 LA1~LA4]
[Ref: 共享规约 19 etl 场景 → 本地路由]
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from apps.deep_strike.lighthouse._base import BaseLighthouseScene
from apps.deep_strike.lighthouse.schemas import (
    CallMetadata,
    SnifferCluster,
    SnifferInput,
    SnifferOutput,
)

_SYSTEM_PROMPT = """你是 Lighthouse-Alpha 的 The Sniffer 主题嗅探员。

任务：从给定原文集合中识别"题材簇"——多篇文本反复出现的产业链/技术/政策关键词。

约束：
1) 仅输出 JSON，不要任何解释；
2) 每个簇必须 ≥ 2 篇文本支持；
3) freq_growth_pct = 当前窗口词频 / 历史 baseline - 1（无 baseline 时给 0.5 缺省）；
4) confidence 反映该簇的"题材成色"：政策硬规则 + 产业链需求落地 → 0.8+；纯炒作概念 → ≤ 0.4。

输出 schema：
{
  "clusters": [
    {
      "keyword": "...",
      "summary": "≥10 字一句话",
      "freq_growth_pct": 0.30,
      "confidence": 0.75,
      "sample_doc_idx": [0, 3, 5]
    }
  ]
}
"""


class TheSniffer(BaseLighthouseScene):
    scene = "etl"
    prompt_template_id = "the_sniffer_v1"

    def build_messages(self, payload: SnifferInput) -> list[dict[str, str]]:
        snippets = []
        for i, t in enumerate(payload.raw_texts[:50]):
            snippets.append(f"[doc {i}] {t[:500]}")
        user = (
            f"窗口：{payload.window_start} ~ {payload.window_end}\n"
            f"来源 hint：{payload.source_hint or 'mixed'}\n"
            f"原文片段（共 {len(payload.raw_texts)} 条，截取前 50）：\n"
            + "\n".join(snippets)
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def parse(self, raw_json: dict, payload: SnifferInput, metadata: CallMetadata) -> SnifferOutput:
        clusters_raw = raw_json.get("clusters", [])
        clusters: list[SnifferCluster] = []
        for c in clusters_raw:
            keyword = c.get("keyword", "").strip()
            if not keyword:
                continue
            cid = hashlib.md5(
                f"{keyword}{payload.window_start}".encode()
            ).hexdigest()[:12]
            clusters.append(
                SnifferCluster(
                    cluster_id=cid,
                    keyword=keyword,
                    summary=c.get("summary", keyword)[:200],
                    freq_growth_pct=float(c.get("freq_growth_pct", 0.0)),
                    confidence=float(c.get("confidence", 0.5)),
                    sample_doc_idx=[int(i) for i in c.get("sample_doc_idx", [])],
                )
            )
        return SnifferOutput(
            clusters=clusters,
            total_docs=len(payload.raw_texts),
            metadata=metadata,
        )

    def fallback(
        self, payload: SnifferInput, metadata: CallMetadata, *, reason: str
    ) -> SnifferOutput:
        """fallback：本地 bigram 词频简化簇。"""
        counter: Counter[str] = Counter()
        for t in payload.raw_texts:
            tokens = [w for w in t.split() if len(w) >= 2]
            counter.update(tokens)
            for i in range(len(tokens) - 1):
                counter[f"{tokens[i]}{tokens[i + 1]}"] += 1

        top = counter.most_common(3)
        clusters: list[SnifferCluster] = []
        for rank, (kw, freq) in enumerate(top):
            if freq < 2:
                continue
            cid = hashlib.md5(
                f"{kw}{payload.window_start}".encode()
            ).hexdigest()[:12]
            clusters.append(
                SnifferCluster(
                    cluster_id=cid,
                    keyword=kw,
                    summary=f"[fallback] 词频 top{rank + 1}：{kw}（{freq} 次）",
                    freq_growth_pct=0.0,
                    confidence=0.3,
                    sample_doc_idx=[],
                )
            )
        return SnifferOutput(clusters=clusters, total_docs=len(payload.raw_texts), metadata=metadata)
