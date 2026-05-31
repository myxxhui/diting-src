#!/usr/bin/env python3
"""step_12 tier-2：对 K3s 生产 Copilot 做 ①~④ 验收 curl。

读取 diting-infra/prod.conn 的 PUBLIC_IP / REDIS_URL。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_prod_conn() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    conn = root.parent / "diting-infra" / "prod.conn"
    if not conn.is_file():
        conn = root / "diting-infra" / "prod.conn"
    out: dict[str, str] = {}
    if conn.is_file():
        for line in conn.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _get(url: str, timeout: float = 20.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    conn = _load_prod_conn()
    ip = os.environ.get("PUBLIC_IP") or conn.get("PUBLIC_IP", "127.0.0.1")
    port = os.environ.get("COPILOT_NODE_PORT", "30080")
    base = f"http://{ip}:{port}"
    failures: list[str] = []

    print(f"▶ [copilot-step12-tier2-verify] base={base}")

    code, body = _get(f"{base}/")
    if code != 200:
        failures.append(f"GET / → {code}")
    else:
        for label in ("持仓监管", "行情解析及规划", "产业图谱"):
            if label not in body:
                failures.append(f"导航缺 {label}")

    code, _ = _get(f"{base}/planning")
    if code != 200:
        failures.append(f"GET /planning → {code}")

    code, body = _get(f"{base}/api/campaigns")
    if code != 200:
        failures.append(f"GET /api/campaigns → {code}: {body[:200]}")
    else:
        try:
            camps = json.loads(body)
        except json.JSONDecodeError:
            failures.append("GET /api/campaigns 非 JSON")
            camps = []
        if not camps:
            failures.append("GET /api/campaigns 为空（需 Pod bootstrap 跑 campaign 导入）")
        elif not camps[0].get("symbols"):
            failures.append("campaign 无 symbols")
        else:
            cid = camps[0]["id"]
            sym = camps[0]["symbols"][0]["symbol"]
            code2, body2 = _get(f"{base}/api/campaigns/{cid}/symbols/{sym}", timeout=30.0)
            if code2 != 200:
                failures.append(f"GET dossier → {code2}")
            else:
                dossier = json.loads(body2)
                for k in ("quote", "phase", "niche", "moat", "risk", "monitors"):
                    if k not in dossier:
                        failures.append(f"dossier 缺 {k}")
            code3, body3 = _get(f"{base}/api/campaigns/{cid}/monitors")
            if code3 != 200:
                failures.append(f"GET monitors → {code3}")
            else:
                mons = json.loads(body3)
                pillars = {m["pillar"] for m in mons}
                if not pillars >= {"moat", "catalyst", "risk"}:
                    failures.append(f"三支柱不齐: {pillars}")

    if failures:
        print("❌ tier-2 生产验收失败:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ tier-2 生产验收通过（①~④ HTTP）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
