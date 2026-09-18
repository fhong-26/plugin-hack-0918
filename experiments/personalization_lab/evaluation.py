"""Deterministic grading, paired uncertainty, and validation-only selection."""
from __future__ import annotations

from collections import defaultdict
import math
import random
import statistics


def selected(result: dict) -> str:
    return result.get("route_id") if result.get("status") == "selected" else "defer"


def grade(row: dict, result: dict) -> dict:
    route = selected(result)
    error = result.get("reason_code") not in {"MODEL_SELECTION", "MODEL_DEFER", "EXACT_SYMBOL", "KNOWN_FILENAME", "SAVED_PREFERENCE", "ONLY_CANDIDATE"}
    return {"id": row["id"], "user_id": row["user_id"], "family_id": row["family_id"],
            "domain_id": row["domain_id"], "kind": row["kind"], "split": row["split"],
            "selected": route, "preferred": row["preferred_route"],
            "preference_match": not error and route == row["preferred_route"],
            "acceptable": not error and route in row["acceptable_routes"],
            "deferred": route == "defer", "error": error, "result": result}


def summary(rows: list[dict]) -> dict:
    def measure(items):
        return {"matched": sum(bool(r["preference_match"]) for r in items), "total": len(items),
                "rate": sum(bool(r["preference_match"]) for r in items) / len(items) if items else None}
    preference = [r for r in rows if r["kind"] == "preference"]
    objective = [r for r in rows if r["kind"] == "objective"]
    users = sorted({r["user_id"] for r in rows})
    latencies = sorted(r["result"].get("inference_ms", r["result"].get("elapsed_ms", 0)) for r in rows)
    return {"all": measure(rows), "preference": measure(preference), "objective": measure(objective),
            "per_user": {u: measure([r for r in preference if r["user_id"] == u]) for u in users},
            "acceptable": sum(bool(r["acceptable"]) for r in rows), "errors": sum(r["error"] for r in rows),
            "defers": sum(r["deferred"] for r in rows),
            "median_ms": statistics.median(latencies) if latencies else None,
            "p95_ms": latencies[min(len(latencies) - 1, math.ceil(len(latencies) * 0.95) - 1)] if latencies else None}


def paired_delta(before: list[dict], after: list[dict], *, seed: int = 31, samples: int = 2000) -> dict:
    left = {row["id"]: row for row in before if row["kind"] == "preference"}
    right = {row["id"]: row for row in after if row["kind"] == "preference"}
    if left.keys() != right.keys() or not left:
        raise ValueError("Paired comparisons require exactly the same nonempty test cohort")
    clusters = defaultdict(list)
    for key, row in left.items():
        # Resample whole scenario families, including all users for that family.
        clusters[row["family_id"]].append(int(right[key]["preference_match"]) - int(row["preference_match"]))
    keys = list(clusters)
    rng = random.Random(seed)
    deltas = []
    for _ in range(samples):
        values = [value for key in rng.choices(keys, k=len(keys)) for value in clusters[key]]
        deltas.append(sum(values) / len(values))
    deltas.sort()
    improvements = sum(not left[k]["preference_match"] and right[k]["preference_match"] for k in left)
    regressions = sum(left[k]["preference_match"] and not right[k]["preference_match"] for k in left)
    return {"before": sum(r["preference_match"] for r in left.values()),
            "after": sum(r["preference_match"] for r in right.values()), "total": len(left),
            "improvements": improvements, "regressions": regressions,
            "delta_percentage_points": 100 * (improvements - regressions) / len(left),
            "bootstrap_95_percent_interval_pp": [100 * deltas[int(samples * 0.025)], 100 * deltas[int(samples * 0.975)]],
            "cluster_count": len(keys), "note": "Exploratory synthetic-family bootstrap; templates remain correlated"}


def validation_gate(before: list[dict], after: list[dict]) -> dict:
    if {r["id"] for r in before} != {r["id"] for r in after} or not before:
        raise ValueError("Validation cohorts differ or are empty")
    if any(r["split"] != "validation" for r in before + after):
        raise ValueError("Activation must never inspect training or final test labels")
    baseline, candidate = summary(before), summary(after)
    passed = (candidate["preference"]["total"] >= 6
              and candidate["preference"]["matched"] > baseline["preference"]["matched"]
              and candidate["objective"]["matched"] >= baseline["objective"]["matched"]
              and candidate["errors"] <= baseline["errors"])
    return {"passed": passed, "baseline": baseline, "candidate": candidate,
            "criterion": "Strict preference improvement, no objective regression, no additional errors; validation only"}
