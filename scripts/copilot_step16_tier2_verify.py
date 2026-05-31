#!/usr/bin/env python3
"""step_16 tier-2：K3s 生产 ⑨ 规划中证伪与持续监控验收。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
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


def _get(url: str, timeout: float = 30.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _post_form(url: str, data: dict[str, str], timeout: float = 120.0) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    from scripts.copilot_step15_tier2_verify import main as step15_main

    if step15_main() != 0:
        print("❌ step_15 基线未通过，跳过 step_16 增量验收")
        return 1

    conn = _load_prod_conn()
    ip = os.environ.get("PUBLIC_IP") or conn.get("PUBLIC_IP", "127.0.0.1")
    port = os.environ.get("COPILOT_NODE_PORT", "30080")
    base = f"http://{ip}:{port}"
    failures: list[str] = []

    print(f"▶ [copilot-step16-tier2-verify] base={base}")

    code, body = _get(f"{base}/api/campaigns")
    if code != 200:
        failures.append(f"GET campaigns → {code}")
        campaign_id = 1
        sym = "601138"
    else:
        camps = json.loads(body)
        campaign_id = camps[0]["id"] if camps else 1
        sym = camps[0]["symbols"][0]["symbol"] if camps and camps[0].get("symbols") else "601138"

    code_e, _ = _post_form(
        f"{base}/api/campaigns/{campaign_id}/falsify/ensure-default",
        {"symbol": sym},
    )
    if code_e not in (200, 201):
        failures.append(f"POST falsify/ensure-default → {code_e}")

    code_f, body_f = _get(f"{base}/api/campaigns/{campaign_id}/falsify")
    if code_f != 200:
        failures.append(f"GET falsify → {code_f}")
    else:
        tasks = json.loads(body_f)
        types = {t.get("falsify_type") for t in tasks}
        if not {"moat", "niche", "catalyst", "risk"}.issubset(types):
            failures.append(f"4 类证伪不齐: {types}")
        if any(t.get("verdict") == "ok" and not t.get("last_checked_at") for t in tasks):
            failures.append("verdict=ok 但缺 last_checked_at")

    code_r, body_r = _get(f"{base}/api/campaigns/{campaign_id}/readiness")
    if code_r != 200:
        failures.append(f"GET readiness → {code_r}")
    else:
        readiness = json.loads(body_r)
        if readiness.get("human_confirmation_required") is not True:
            failures.append("readiness 缺 human_confirmation_required")

    code_c, body_c = _get(f"{base}/api/campaigns/{campaign_id}/cognitive/{sym}")
    if code_c != 200:
        failures.append(f"GET cognitive → {code_c}")

    code_p, _ = _post_form(f"{base}/api/campaigns/{campaign_id}/promote-executing", {})
    if code_p != 400:
        failures.append(f"无 human_confirmed 应 400，实际 {code_p}")

    if failures:
        print("❌ step_16 tier-2 生产验收失败:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ step_16 tier-2 生产验收通过（⑨ 证伪 + 就绪度 + 人工确认闸）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
