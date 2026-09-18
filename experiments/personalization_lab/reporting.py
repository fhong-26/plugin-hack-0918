"""Export auditable synthetic results and a standalone report figure."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import statistics

from rippletide.personalization import atomic_json, read_json


def audit_reference(root: Path) -> dict:
    cases, calls, missing = 0, [], []
    for path in sorted(root.glob("*/result.json")):
        cases += 1
        record = read_json(path)
        rollout = record.get("evidence", {}).get("parent_rollout")
        if not rollout or not Path(rollout).is_file():
            missing.append(path.parent.name)
            continue
        for line in Path(rollout).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            payload = event.get("payload", {})
            if payload.get("type") in {"function_call", "custom_tool_call", "web_search_call", "computer_call"}:
                calls.append({"case": path.parent.name, "name": payload.get("name"), "type": payload["type"]})
    return {"cases": cases, "missing_rollouts": missing, "observed_calls": calls,
            "verified_no_tool_calls": cases > 0 and not calls and not missing}


def export(component_run: Path, reference_run: Path, output: Path, task_root: Path | None = None,
           rules_reference: Path | None = None, dataset: Path | None = None) -> dict:
    measured = read_json(component_run / "results.json")
    grades = read_json(component_run / "grades.json")
    reference = read_json(reference_run / "results.json")
    output.mkdir(parents=True, exist_ok=True)
    result = {"component": measured, "codex_reference": {
        "manifest": reference["manifest"], "summary": reference["summary"],
        "complete": reference["complete"], "audit": audit_reference(reference_run)},
        "training": {}, "validation": {}, "tasks": {}, "probability_examples": [],
        "test_cases": {arm: [{k: row[k] for k in ("id", "user_id", "family_id", "kind",
            "selected", "preferred", "preference_match", "acceptable", "deferred", "error")}
            for row in splits["test"]] for arm, splits in grades.items()}}
    environment = component_run / "environment.json"
    if environment.exists():
        result["environment"] = read_json(environment)
    resources = component_run / "resources.jsonl"
    if resources.exists():
        samples = [json.loads(line) for line in resources.read_text(encoding="utf-8").splitlines() if line.strip()]
        if samples:
            result["resources"] = {
                "samples": len(samples), "first_sample_at": samples[0]["timestamp"],
                "last_sample_at": samples[-1]["timestamp"],
                "observed_wall_seconds": (datetime.fromisoformat(samples[-1]["timestamp"]) -
                                           datetime.fromisoformat(samples[0]["timestamp"])).total_seconds(),
                "peak_process_rss_bytes": max(max(s["rss_bytes"], s.get("peak_rss_bytes") or 0) for s in samples),
                "minimum_system_available_bytes": min(s["system_available_bytes"] for s in samples),
                "last_process_cpu_seconds": samples[-1]["cpu_seconds"],
                "note": "Samples cover the stated interval; Windows peak memory and cumulative CPU counters cover the process lifetime. Not energy or monetary cost."}
            gaps = []
            for previous, following in zip(samples, samples[1:]):
                seconds = (datetime.fromisoformat(following["timestamp"]) -
                           datetime.fromisoformat(previous["timestamp"])).total_seconds()
                if seconds > 60:
                    gaps.append({"from": previous["timestamp"], "to": following["timestamp"],
                                 "wall_seconds": seconds,
                                 "process_cpu_seconds_increase": following["cpu_seconds"] - previous["cpu_seconds"]})
            result["resources"]["sampling_gaps_over_60_seconds"] = gaps
    # Separate actual neural forward timings from fast rule decisions. Residual
    # results reuse memory's forward timing; the adjustment overhead is unmeasured.
    result["model_inference"] = {}
    for arm, splits in grades.items():
        times = sorted(r["result"]["inference_ms"] for r in splits["test"]
                       if r["kind"] != "rule" and "inference_ms" in r["result"])
        result["model_inference"][arm] = {"timed_test_cases": len(times),
            "median_ms": statistics.median(times) if times else None,
            "maximum_ms": max(times) if times else None,
            "within_production_two_seconds": sum(t <= 2000 for t in times),
            "residual_adjustment_overhead_included": False if arm == "residual" else None}
    if rules_reference:
        control = read_json(rules_reference / "results.json")
        result["saved_rules_reference"] = {k: v for k, v in control.items() if k != "grades"}
    # Fixed first preference case per user and operation, not cherry-picked by
    # whether a treatment helped. The same case/order is used in every arm.
    from .dataset import read_rows
    if dataset and read_json(dataset / "manifest.json")["dataset_digest"] != measured["manifest"]["dataset"]["dataset_digest"]:
        raise ValueError("Probability example dataset differs from the measured cohort")
    test_rows = {r["id"]: r for r in read_rows(dataset, "test")} if dataset else {}
    seen = set()
    for row in grades["current"]["test"]:
        source = test_rows.get(row["id"])
        if source is None or row["kind"] != "preference":
            continue
        key = (row["user_id"], source["packet"]["operation"])
        if key in seen:
            continue
        seen.add(key)
        example = {"id": row["id"], "user": row["user_id"], "operation": key[1],
                   "goal": source["packet"]["goal"], "preferred": row["preferred"], "arms": {}}
        for arm in grades:
            treatment = next(g for g in grades[arm]["test"] if g["id"] == row["id"])
            raw = treatment["result"]
            example["arms"][arm] = {"selected": treatment["selected"], "probabilities":
                dict(zip(raw.get("candidate_ids", []), raw.get("candidate_probabilities", [])))}
        result["probability_examples"].append(example)
    for user in measured["manifest"]["users"]:
        adapter = component_run / "adapters" / user
        result["training"][user] = {"lora": read_json(adapter / "training.json"),
            "adapter_bytes": sum(p.stat().st_size for p in adapter.glob("*.safetensors")),
            "adapter_identity": read_json(adapter / "rippletide_adapter.json")}
        result["validation"][user] = {"residual": read_json(component_run / "policies" / f"{user}-validation.json"),
                                      "lora": read_json(adapter / "validation.json")}
    if task_root:
        for path in sorted(task_root.glob("*/task-results.json")):
            task = read_json(path)
            routes = task["routing_decisions"]
            result["tasks"][path.parent.name] = {"level": task["manifest"]["level"],
                "wall_seconds": task["session"]["wall_seconds"], "status": task["session"]["status"],
                "acceptance": task["acceptance"], "completed_specialists": task["completed_specialists"],
                "task_requirements_verified": task["task_requirements_verified"],
                "fixture_tool_counts": dict(Counter(e["server"] + "." + e["tool"] for e in task["actual_fixture_calls"])),
                "hook_event_count": task["hook_event_count"], "routing_decision_count": len(routes),
                "route_reasons": dict(Counter(e.get("response", {}).get("reason_code") for e in routes)),
                "initial_snapshot_digest": task["manifest"]["initial_snapshot_digest"],
                "route_deadline_seconds": task["manifest"]["route_deadline_seconds"]}
    atomic_json(output / "personalization-results.json", result)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    names = ["Current\nQwen", "Qwen +\nmemory", "Qwen +\nresidual", "Qwen +\nLoRA", "Codex\nreference"]
    stats = [measured["results"][arm]["test"]["preference"] for arm in ("current", "memory", "residual", "lora")]
    stats.append(reference["summary"]["preference"])
    objectives = [measured["results"][arm]["test"]["objective"] for arm in ("current", "memory", "residual", "lora")]
    objectives.append(reference["summary"]["objective"])
    colors = ["#737B86", "#4477AA", "#228833", "#AA3377", "#CCBB44"]
    if rules_reference:
        names.append("Saved rules\n(diagnostic)")
        stats.append(control["summary"]["preference"])
        objectives.append(control["summary"]["objective"])
        colors.append("#66CCEE")
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.5))
    fig.subplots_adjust(left=0.065, right=0.99, bottom=0.23, top=0.90, wspace=0.25)
    for ax, values, title in zip(axes, [stats, objectives], ["Preference-sensitive choices", "Task-determined choices"]):
        bars = ax.bar(names, [s["matched"] for s in values], color=colors)
        for bar, s in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                    f'{s["matched"]}/{s["total"]}', ha="center", fontweight="bold", fontsize=9)
        ax.set_ylim(0, values[0]["total"] + 4)
        ax.set_ylabel("Matching choices on identical held-out cases")
        ax.set_title(title, loc="left", pad=15)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", labelsize=8)
        ax.yaxis.grid(True, alpha=0.2)
    fig.text(0.02, 0.025, "Qwen3-0.6B CPU; 3 synthetic profiles; 12 training examples/profile.\n"
             "Memory is the training control. Codex reference selects only; target tools are not executed.", fontsize=9, va="bottom")
    fig.savefig(output / "personalization-preference-matches.png", dpi=180, bbox_inches="tight")
    fig.savefig(output / "personalization-preference-matches.svg", bbox_inches="tight")
    plt.close(fig)
    return {"results": str(output / "personalization-results.json"), "figure": str(output / "personalization-preference-matches.png")}
