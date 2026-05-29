"""Holdout 守门：manifest SHA256；训练数据（JSONL 或 JSON 数组）含 Holdout symbol 则失败。

环境变量 CRYO_HOLDOUT_DIR 可覆盖目录。
"""
from __future__ import annotations

import argparse
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


def verify_manifest() -> bool:
    holdout_dir = _holdout_root()
    manifest_path = holdout_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"❌ 缺少 manifest: {manifest_path}")
        return False
    manifest = json.loads(manifest_path.read_text())
    ok = True
    for case in manifest["cases"]:
        p = holdout_dir / case["filename"]
        if not p.exists():
            print(f"❌ 缺失 {case['filename']}")
            ok = False
            continue
        expected = case["sha256"]
        actual = _sha256(p)
        if expected != actual:
            print(f"❌ 篡改 {case['filename']}: expected={expected[:12]} actual={actual[:12]}")
            ok = False
    if ok:
        print(f"✅ Holdout 验证通过（{len(manifest['cases'])} 案例 / SHA256 匹配）")
    return ok


def _load_holdout_symbols() -> set[str]:
    holdout_dir = _holdout_root()
    syms: set[str] = set()
    for f in holdout_dir.glob("H*.json"):
        syms.add(json.loads(f.read_text())["symbol"])
    return syms


def _iter_training_items(tf: Path) -> list[tuple[str, dict]]:
    """支持 JSON 数组文件或 JSONL。返回 [(label, item), ...]。"""
    raw = tf.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    out: list[tuple[str, dict]] = []
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"{tf} JSON 根应为数组")
        for i, item in enumerate(data):
            if isinstance(item, dict):
                out.append((f"idx:{i}", item))
        return out
    for ln, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        out.append((f"line:{ln}", json.loads(line)))
    return out


def check_training_data(training_files: list[Path]) -> bool:
    holdout_syms = _load_holdout_symbols()
    ok = True
    for tf in training_files:
        try:
            items = _iter_training_items(tf)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            print(f"❌ 无法读取 {tf}: {exc}")
            ok = False
            continue
        for label, item in items:
            meta = item.get("metadata") or {}
            sym = meta.get("symbol") or item.get("symbol")
            if sym in holdout_syms:
                print(f"❌ {tf!s}:{label} 含 Holdout symbol={sym}")
                ok = False
    if ok:
        print("✅ 训练集不含 Holdout symbol")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="校验 manifest SHA256")
    ap.add_argument("--check-training-data", nargs="*", type=Path, default=[])
    args = ap.parse_args()
    ok = True
    if args.verify or not args.check_training_data:
        ok = verify_manifest() and ok
    if args.check_training_data:
        ok = check_training_data(args.check_training_data) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    sys.exit(main())
