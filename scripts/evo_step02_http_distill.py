"""D5 step02 HTTP 蒸馏冒烟（TestClient，无需手动起服务）。

验证 /api/distill/health + /api/distill/single（dry_run 或真实 Sonnet）。

[Ref: 03_/05_维度五/.../step_02 §9]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(__file__).parents[1] / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        pass


def main() -> int:
    _load_dotenv()
    os.environ.setdefault("SUPER_EVO_WANDB_MODE", "offline")

    from fastapi.testclient import TestClient
    from apps.super_evo.main import app

    client = TestClient(app)

    print("▶ GET /api/distill/health")
    r = client.get("/api/distill/health")
    print(f"  status={r.status_code} body={r.json()}")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    has_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    print(f"  ANTHROPIC_KEY={'✅' if has_key else '⚠️ dry_run'}")

    print("▶ POST /api/distill/single")
    payload = {
        "task_type": "financial_fraud",
        "raw_data": {"symbol": "603556", "text": "W2 HTTP 冒烟测试"},
        "sample_id": "w2_http_smoke_001",
    }
    r2 = client.post("/api/distill/single", json=payload)
    print(f"  status={r2.status_code}")
    if r2.status_code != 200:
        print(f"  error={r2.text[:300]}")
        return 1
    data = r2.json()
    assert "output" in data
    print(f"  teacher_model={data.get('metadata', {}).get('teacher_model')}")
    print("  ✅ HTTP 蒸馏链路通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
