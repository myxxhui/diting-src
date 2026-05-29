"""注入 mock thesis_proposed — 已禁用（no-mock-policy）."""
import sys

if __name__ == "__main__":
    print("❌ inject_mock_thesis 已禁用（no-mock-policy）。", file=sys.stderr)
    raise SystemExit(2)
