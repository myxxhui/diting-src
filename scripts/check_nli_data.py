"""NLI 训练数据质量检查脚本。[Ref: watch-step05-data-check]"""
from __future__ import annotations

import collections
import json


def load(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


train = load("training/data/narrative_nli/train.jsonl")
dev   = load("training/data/narrative_nli/dev.jsonl")
hold  = load("training/data/narrative_nli/holdout.jsonl")

total = len(train) + len(dev) + len(hold)
print(f"  train={len(train)}  dev={len(dev)}  holdout={len(hold)}  total={total}")

assert len(train) >= 100, f"train 须 >= 100，实际 {len(train)}"
assert len(dev)   >= 20,  f"dev 须 >= 20，实际 {len(dev)}"
assert len(hold)  >= 30,  f"holdout 须 >= 30，实际 {len(hold)}"

labels = collections.Counter(r["output"] for r in train)
print(f"  标签分布: {dict(labels)}")

valid_labels = {"entailment", "neutral", "contradiction"}
bad = set(r["output"] for r in train) - valid_labels
assert not bad, f"非法标签: {bad}"

print("✅ 数据质量检查通过（train/dev/holdout 行数 + 标签合法）")
