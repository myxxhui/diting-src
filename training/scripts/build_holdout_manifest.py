"""根据 training/data/holdout/*.json 生成 manifest.json（SHA256）。

环境变量 CRYO_HOLDOUT_DIR 可覆盖目录。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _holdout_root() -> Path:
    env = os.environ.get("CRYO_HOLDOUT_DIR")
    if env:
        return Path(env)
    return _REPO / "training" / "data" / "holdout"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    holdout_dir = _holdout_root()
    manifest = holdout_dir / "manifest.json"
    cases = []
    for p in sorted(holdout_dir.glob("H*.json")):
        cid = json.loads(p.read_text())["case_id"]
        cases.append({"case_id": cid, "filename": p.name, "sha256": _sha256(p)})
    manifest.write_text(json.dumps({"version": 1, "cases": cases}, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {manifest} ({len(cases)} cases)")


if __name__ == "__main__":
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    main()
