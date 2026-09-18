"""Independent black-box session assertions, executed outside the test project."""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    sys.path.insert(0, args.workspace)
    checks = []
    try:
        from session_app import SessionStore, validate_identity

        cases = [("before_expiry", "active", 99, "ada"), ("exact_deadline", "active", 100, None), ("after_expiry", "active", 101, None), ("revoked", "revoked", 99, None), ("missing", "missing", 99, None)]
        for name, session_id, now, expected in cases:
            store = SessionStore([{"id": "active", "user_id": "ada", "expires_at": 100, "revoked": False}, {"id": "revoked", "user_id": "ben", "expires_at": 100, "revoked": True}])
            actual = validate_identity(store, session_id, now)
            checks.append({"name": name, "passed": actual == expected, "actual": actual, "expected": expected})
    except Exception as exc:
        checks.append({"name": "public_api", "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    result = {"status": "passed" if checks and all(item["passed"] for item in checks) else "failed", "checks": checks}
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
