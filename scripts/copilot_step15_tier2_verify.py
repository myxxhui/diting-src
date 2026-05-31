#!/usr/bin/env python3
"""step_15 tier-2：K3s 生产 ⑧ 滚动路线图双层锚定验收。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
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
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
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
    from scripts.copilot_step14_tier2_verify import main as step14_main

    if step14_main() != 0:
        print("❌ step_14 基线未通过，跳过 step_15 增量验收")
        return 1

    conn = _load_prod_conn()
    ip = os.environ.get("PUBLIC_IP") or conn.get("PUBLIC_IP", "127.0.0.1")
    port = os.environ.get("COPILOT_NODE_PORT", "30080")
    base = f"http://{ip}:{port}"
    failures: list[str] = []

    print(f"▶ [copilot-step15-tier2-verify] base={base}")

    code, body = _get(f"{base}/api/campaigns")
    if code != 200:
        failures.append(f"GET campaigns → {code}")
        campaign_id = 1
    else:
        camps = json.loads(body)
        campaign_id = camps[0]["id"] if camps else 1

    d1 = (date.today() + timedelta(days=45)).isoformat()
    d2 = (date.today() + timedelta(days=50)).isoformat()
    for sym, ad, seq in (("601138", d1, "1"), ("300308", d2, "2")):
        code_t, _ = _post_form(
            f"{base}/api/campaigns/{campaign_id}/timeline",
            {
                "symbol": sym,
                "anchor_date": ad,
                "title": f"云验收 {sym} 爆发",
                "sequence_no": seq,
                "target_weight_pct": "60",
            },
        )
        if code_t not in (200, 201):
            failures.append(f"POST timeline {sym} → {code_t}")

    code_tl, body_tl = _get(f"{base}/api/campaigns/{campaign_id}/timeline")
    if code_tl != 200:
        failures.append(f"GET timeline → {code_tl}")
    else:
        items = json.loads(body_tl)
        flags = [f for it in items for f in (it.get("feasibility_flags") or [])]
        if "window_overlap" not in flags:
            failures.append(f"缺 window_overlap flag: {flags}")

    code_r, body_r = _post_form(f"{base}/api/campaigns/{campaign_id}/regime/assess", {})
    if code_r not in (200, 201):
        failures.append(f"POST regime/assess → {code_r}")
    else:
        regimes = json.loads(body_r)
        if not regimes:
            failures.append("regime/assess 无结果")
        elif regimes[0].get("confirm_state") != "inferred":
            failures.append("regime confirm_state 非 inferred")

    code_m, body_m = _get(f"{base}/api/campaigns/{campaign_id}/monitors")
    if code_m == 200:
        mons = json.loads(body_m)
        _ = [m for m in mons if m.get("falsify_type") == "regime"]
    else:
        failures.append(f"GET monitors → {code_m}")

    if failures:
        print("❌ step_15 tier-2 生产验收失败:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ step_15 tier-2 生产验收通过（⑧ 时间线 + 合理性 + regime inferred）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
