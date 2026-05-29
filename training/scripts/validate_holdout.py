"""校验 50 个 Holdout JSON + 引擎分布 30/10/10 + manifest。

环境变量 CRYO_HOLDOUT_DIR 可覆盖目录。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from apps.cryo_guard.holdout.schema import HoldoutCaseFile  # noqa: E402


def _holdout_root() -> Path:
    env = os.environ.get("CRYO_HOLDOUT_DIR")
    if env:
        return Path(env)
    return _REPO / "training" / "data" / "holdout"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    d = _holdout_root()
    files = sorted(d.glob("H*.json"))
    if len(files) != 50:
        print(f"❌ Holdout 文件数应为 50，实际 {len(files)}")
        return 1
    engines = Counter()
    for f in files:
        obj = HoldoutCaseFile.model_validate_json(f.read_text())
        engines[obj.target_engine] += 1
    if engines["financial_fraud"] != 30 or engines["shareholder_integrity"] != 10 or engines["related_party"] != 10:
        print(f"❌ 引擎分布错误: {dict(engines)}")
        return 1
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        print(f"❌ 缺少 manifest: {manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text())
    for case in manifest["cases"]:
        p = d / case["filename"]
        if not p.exists():
            print(f"❌ 缺失 {case['filename']}")
            return 1
        if _sha256(p) != case["sha256"]:
            print(f"❌ SHA256 不匹配 {case['filename']}")
            return 1
    print("✅ Holdout 验证通过（50 案例 / SHA256 匹配 / 引擎分布 30+10+10）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
