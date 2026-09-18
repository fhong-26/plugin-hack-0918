#!/usr/bin/env python3
"""Summarize every retained driver attempt, including failed and unreviewed runs."""

import argparse
import json
from pathlib import Path


def cohort(rows):
    complete = all(row["required_interventions"] is not None for row in rows)
    successes = sum(row["successful_without_required_intervention"] is True for row in rows)
    return {
        "attempts": len(rows), "successful_without_required_intervention": successes,
        "zero_intervention_success_rate": successes / len(rows) if rows else None,
        "mean_required_interventions": sum(row["required_interventions"] for row in rows) / len(rows) if rows and complete else None,
        "ledger_complete": complete,
        "unreviewed_or_missing_reports": sum(row["outcome"] == "unknown" for row in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path(__file__).resolve().parents[1] / ".uat-runs")
    args = parser.parse_args()
    rows = []
    for driver in sorted(args.runs_root.glob("*/pilot-run.json")):
        run = driver.parent
        manifest = json.loads((run / "run.json").read_text())
        report_path = run / "report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        rows.append({
            "run_id": run.name, "scenario": manifest["scenario"], "variant": manifest["variant"],
            "normal_cohort": manifest["scenario_definition"].get("normal_cohort", False),
            "outcome": report.get("task_outcome", "unknown"),
            "acceptance": report.get("scenario_acceptance_status", "unknown"),
            "required_interventions": report.get("required_interventions"),
            "total_interactions": report.get("total_interactions"),
            "successful_without_required_intervention": report.get("successful_without_required_intervention"),
            "qwen_execution_categories": report.get("qwen_execution_categories", []),
            "usage_scope": report.get("usage_scope", "unknown"),
            "usage_complete_for_task": report.get("usage_complete_for_task", False),
        })
    print(json.dumps({"benchmark_validated": False, "all_retained_attempts": cohort(rows),
                      "normal_operation_attempts": cohort([row for row in rows if row["normal_cohort"]]),
                      "verified_qwen_categories": sorted({kind for row in rows for kind in row["qwen_execution_categories"]}),
                      "runs": rows,
                      "note": "Development failures and unreviewed attempts stay in the denominator. One smoke per condition is not a benchmark. Inspect routing-quality caveats separately from application completion."}, indent=2))


if __name__ == "__main__":
    main()
