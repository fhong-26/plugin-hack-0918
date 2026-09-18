"""Paired reports: evidence first, four independent dimensions, safe exports."""
from __future__ import annotations

from collections import Counter
import html
import json
import math
from pathlib import Path
import re

from .storage import digest, read_json, timestamp, write_json
from .trace_evidence import arm_traces, events_at, instant, path_at, native_routes, numeric_usage, hook_calls, supplement_cli_outcomes

VERDICTS = {"correct", "incorrect", "uncertain", "ungradable"}


def private_json(path: Path, value) -> None:
    write_json(path, value)
    path.chmod(0o600)


def load_pair(run: Path) -> dict:
    value = read_json(run / "pair.json")
    if value.get("schema_version") != 1 or set(value.get("arms", {})) != {"baseline", "rippletide"}:
        raise ValueError("pair.json must have schema_version=1 and baseline/rippletide arms")
    return value


def _aggregate(verdicts) -> str:
    values = list(verdicts)
    if "incorrect" in values:
        return "incorrect"
    if not values or all(x == "ungradable" for x in values):
        return "ungradable"
    if any(x in {"uncertain", "ungradable"} for x in values):
        return "uncertain"
    return "correct"


def _routing_metrics(decisions):
    times = sorted(d["elapsed_ms"] for d in decisions if isinstance(d.get("elapsed_ms"), (int, float)) and d["elapsed_ms"] >= 0)
    model = [d for d in decisions if d.get("source") == "model"]
    categories = {}
    for key in ("input_tokens", "output_tokens", "readout_tokens"):
        values = [d.get(key) for d in model]
        categories[key] = sum(values) if values and all(isinstance(x, int) and x >= 0 for x in values) else None
    return {"decision_count": len(decisions), "model_decision_count": len(model),
            "fallback_count": sum(d.get("source") == "fallback" or d.get("status") == "defer" for d in decisions),
            "unlinked_decision_count": sum(not d["linked_call_ids"] for d in decisions),
            "latency_ms": {"count": len(times), "p50": times[math.ceil(len(times) * .5) - 1] if times else None,
                           "p95": times[math.ceil(len(times) * .95) - 1] if times else None, "sum": sum(times) if times else None},
            "small_model_tokens": categories,
            "note": "Small-model routing tokens/readouts and judge tokens are separate from Codex execution usage. No cloud price is inferred."}


def _capabilities(pair: dict) -> list[dict]:
    return [{"id": "native.filename_search", "kind": "native", "description": "Find files by name", "invocation": {"tool": "exec_command"}},
            {"id": "native.lexical_search", "kind": "native", "description": "Search exact text", "invocation": {"tool": "exec_command"}},
            *pair.get("profile", {}).get("tools", {}).get("capabilities", [])]


def capability_for(call: dict, capabilities: list[dict]) -> list[str]:
    if call["kind"] == "mixed_search":
        return sorted("native." + route for route in native_routes(call["arguments"].get("cmd", call["arguments"].get("command", ""))))
    if call["kind"] in {"filename_search", "lexical_search"}:
        return ["native." + call["kind"]]
    matches = []
    for cap in capabilities:
        invocation = cap.get("invocation", {})
        if call["kind"] == "agent" and invocation.get("agent_type") and invocation["agent_type"] == call["arguments"].get("agent_type"):
            matches.append(cap["id"])
        if call["kind"] == "mcp":
            parts = call["tool_name"].split("__", 2)
            if len(parts) == 3 and parts[2] == invocation.get("tool") and (parts[1] == invocation.get("server") or parts[1].endswith("_" + str(invocation.get("server")))):
                matches.append(cap["id"])
    return matches


def _hook_matches(call, event):
    if event.get("call_id") != call["call_id"]:
        return False
    if call.get("turn_id") and event.get("turn_id") != call["turn_id"]:
        return False
    # Some hosts alias a child's session ID to its parent; its actual transcript
    # must then carry the child's ID. Never correlate by parent session alone.
    if event.get("session_id") != call["session_id"] and call["session_id"] not in str(event.get("transcript_path", "")):
        return False
    if isinstance(event.get("tool_input"), dict) and event["tool_input"] != call["arguments"]:
        return False
    return True


def _routing(call, hooks, decisions, enabled):
    if not enabled:
        return {"verdict": "ungradable", "status": "not_applicable_baseline", "decision_id": None}
    if call["kind"] == "routing":
        return {"verdict": "ungradable", "status": "router_control_call", "decision_id": None}
    events = [e for e in hooks if _hook_matches(call, e)]
    blocked = [e for e in events if e.get("event") == "routing_blocked"]
    authorized = [e for e in events if e.get("event") == "routing_authorized"]
    if blocked:
        return {"verdict": "incorrect", "status": "blocked_attempt", "decision_id": None,
                "guard_prevented": True, "reason_codes": [e.get("reason_code") for e in blocked]}
    if not call["capability_ids"]:
        return {"verdict": "ungradable", "status": "outside_registered_coverage", "decision_id": None,
                "observed_by_hook": bool(events)}
    if len(authorized) != 1:
        return {"verdict": "uncertain", "status": "unknown_missing_or_ambiguous_authorization", "decision_id": None}
    auth = authorized[0]
    candidates = [d for d in decisions if d.get("decision_id") == auth.get("decision_id")]
    if len(candidates) != 1:
        return {"verdict": "uncertain", "status": "unknown_missing_or_ambiguous_decision", "decision_id": auth.get("decision_id")}
    decision = candidates[0]
    selected, proposed = instant(decision.get("timestamp")), instant(call.get("timestamp"))
    if selected is None or proposed is None or selected > proposed:
        return {"verdict": "uncertain", "status": "unknown_decision_order", "decision_id": decision["decision_id"]}
    if auth.get("capability_id") not in call["capability_ids"]:
        return {"verdict": "incorrect", "status": "authorized_target_mismatch", "decision_id": decision["decision_id"]}
    if decision.get("status") == "selected" and decision.get("route_id") != auth.get("capability_id"):
        return {"verdict": "incorrect", "status": "selected_target_mismatch", "decision_id": decision["decision_id"]}
    if decision.get("status") not in {"selected", "defer"}:
        return {"verdict": "uncertain", "status": "unknown_decision_status", "decision_id": decision["decision_id"]}
    return {"verdict": "correct", "status": "authorized_fallback" if decision["status"] == "defer" else "authorized_selected",
            "decision_id": decision["decision_id"], "source": decision.get("source"),
            "execution_observed": call["outcome"]["status"] in {"success", "failure"}}


def _task_correctness(acceptance):
    if not isinstance(acceptance, list) or not acceptance:
        return {"verdict": "ungradable", "provenance": "no_acceptance_checks", "scope": "unknown"}
    if any(x.get("status") in {"failed", "timed_out"} or x.get("exit_code") not in {None, 0} for x in acceptance):
        return {"verdict": "incorrect", "provenance": "acceptance_checks", "scope": "configured_checks"}
    passed = all(x.get("status") == "passed" and x.get("exit_code") == 0 for x in acceptance)
    external = all(x.get("independence") == "external" for x in acceptance)
    return {"verdict": "correct" if passed else "uncertain",
            "provenance": "independent-configured-checks" if passed and external else "project-checks-provisional",
            "scope": "configured_checks_only", "complete_specification_proven": False}


def _interventions(run, arm):
    value = arm.get("interventions")
    errors = []
    if isinstance(value, str):
        value, errors = events_at(path_at(run, value))
    complete = arm.get("interventions_complete") is True and isinstance(value, list) and not errors
    counts = Counter(x.get("category", "unknown") for x in value or [] if isinstance(x, dict))
    return {"complete": complete, "required": counts["required"] if complete else None,
            "observed_required": counts["required"], "categories": dict(counts),
            "note": "Planned prompts and setup are not required task interventions. Missing ledger completeness is unknown."}


def build_pair_evidence(run: Path) -> dict:
    """Private normalized evidence shared with the grader; no plugin imports."""
    run = Path(run).resolve()
    pair = load_pair(run)
    result = {"schema_version": 1, "run_id": pair["run_id"], "generated_at": timestamp(),
              "pair": pair, "capabilities": _capabilities(pair), "arms": {}}
    for name, arm in pair["arms"].items():
        traces = arm_traces(run, arm)
        hooks, hook_errors = events_at(path_at(run, arm.get("hook_events")))
        all_router, router_errors = events_at(path_at(run, arm.get("router_events")))
        task_hooks = [e for e in hooks if e.get("phase", "task") == "task"]
        decisions = []
        seen = set()
        for event in all_router:
            if event.get("event") != "routing_decision" or event.get("phase", "task") != "task":
                continue
            response = event.get("response", event)
            if not response.get("decision_id") or digest(event) in seen:
                continue
            seen.add(digest(event))
            decisions.append({**response, "timestamp": event.get("timestamp"), "request": event.get("request", event.get("request_summary")),
                              "request_capture": event.get("request_capture"), "candidates": event.get("candidates"),
                              "candidates_capture": event.get("candidates_capture"),
                              "model": event.get("model", event.get("model_identity")), "linked_call_ids": []})
        calls = hook_calls(traces, task_hooks)
        supplement_cli_outcomes(run, arm, calls)
        for call in calls:
            call["choice_id"] = f"{name}:{call['session_id']}:{call['call_id']}"
            call["capability_ids"] = capability_for(call, result["capabilities"])
            call["routing"] = _routing(call, task_hooks, decisions, name == "rippletide")
            call["execution_success"] = {"success": "correct", "failure": "incorrect", "unknown": "ungradable"}[call["outcome"]["status"]]
            call["tool_choice_correctness"] = {"verdict": "ungradable", "provenance": "not_graded"}
            for decision in decisions:
                if decision["decision_id"] == call["routing"].get("decision_id"):
                    decision["linked_call_ids"].append(call["choice_id"])
        # One-use receipt is essential: a replayed authorization cannot pass twice.
        links = Counter(c["routing"].get("decision_id") for c in calls if c["routing"]["verdict"] == "correct")
        for call in calls:
            if links[call["routing"].get("decision_id")] > 1:
                call["routing"].update(verdict="uncertain", status="unknown_reused_receipt")
        guard_counts = Counter(e.get("event") for e in task_hooks)
        covered = [c for c in calls if c["capability_ids"]]
        guard = {"present": bool(task_hooks), "events": dict(guard_counts), "artifact_errors": hook_errors,
                 "missing_proposals": sum(not any(e.get("event") == "tool_proposed" and _hook_matches(c, e) for e in task_hooks) for c in covered),
                 "blocked_attempts": guard_counts["routing_blocked"], "errors": guard_counts["hook_error"],
                 "unsupported_or_outside_coverage": sum(not c["capability_ids"] and c["kind"] != "routing" for c in calls)}
        guard["opaque_host_containers"] = sum(c["kind"] == "host_container" for c in calls)
        guard["unobserved_host_containers"] = sum(
            not any(other["format"] == "hook" and other["session_id"] == c["session_id"]
                    and instant(other.get("timestamp")) is not None
                    and (instant(c.get("timestamp")) or float("inf")) <= instant(other["timestamp"]) <= (instant(c.get("completed_at")) or float("-inf"))
                    for other in calls)
            for c in calls if c["kind"] == "host_container")
        final = [text for s in traces["sessions"] for text in s["final_messages"]]
        result["arms"][name] = {"status": arm.get("status"), "wall_seconds": arm.get("wall_seconds"),
                                 "exit_code": arm.get("exit_code"), "calls": calls, "decisions": decisions,
                                 "setup_decision_count": sum(e.get("event") == "routing_decision" and e.get("phase") == "preflight" for e in all_router),
                                 "usage": traces["usage"], "interventions": _interventions(run, arm),
                                 "task_correctness": _task_correctness(arm.get("acceptance")),
                                 "guard": guard, "trace_warnings": traces["warnings"], "router_artifact_errors": router_errors,
                                 "final_messages": final, "acceptance": arm.get("acceptance")}
        result["arms"][name]["routing_metrics"] = _routing_metrics(decisions)
        preflight = arm.get("preflight") or {}
        bootstrap = arm.get("bootstrap")
        bootstrap_times = [x.get("wall_seconds") for x in bootstrap] if isinstance(bootstrap, list) else []
        result["arms"][name]["setup"] = {
            "preflight_wall_seconds": preflight.get("wall_seconds"),
            "preflight_usage": arm_traces(run, preflight)["usage"] if preflight else None,
            "bootstrap_wall_seconds": sum(bootstrap_times) if isinstance(bootstrap, list) and all(isinstance(x, (int, float)) for x in bootstrap_times) else None,
            "scope": "setup_excluded_from_task_denominator"}
        result["arms"][name]["observed_settings"] = arm.get("observed_settings")
    return result


def _apply_grades(run, evidence):
    grades = read_json(run / "correctness.json") if (run / "correctness.json").is_file() else {}
    fixtures, fixture_errors = events_at(run / "fixture-grades.jsonl")
    audits, audit_errors = events_at(run / "correctness-audit.jsonl")
    calls = {c["choice_id"]: c for a in evidence["arms"].values() for c in a["calls"]}
    # Preserve the frozen grade, but never carry it onto a changed decision card.
    from .correctness import judge_cards
    cards, _ = judge_cards(evidence)
    context_hashes = {c["choice_id"]: digest(c) for c in cards["decisions"]}
    old_cards = {}
    old_input = path_at(run, grades.get("evidence_directory"))
    if old_input and (old_input / "input.json").is_file():
        old_cards = {c["choice_id"]: digest(c) for c in read_json(old_input / "input.json").get("decisions", [])}
    for grade in grades.get("grades", []):
        if grade.get("choice_id") in calls and grade.get("verdict") in VERDICTS:
            applied = {**grade, "provenance": "automated-provisional"}
            identifier = grade.get("anonymous_choice_id")
            prior_hash = grade.get("context_sha256") or old_cards.get(identifier)
            if grade["verdict"] != "ungradable" and prior_hash != context_hashes.get(identifier):
                applied.update(verdict="ungradable", reason="Decision-time evidence changed or was not bound to this grade; regrading is required.",
                               original_verdict=grade["verdict"])
            calls[grade["choice_id"]]["tool_choice_correctness"] = applied
    for record in fixtures:
        if record.get("provenance") != "fixture-approved" or not record.get("evidence"):
            continue
        if record.get("choice_id") in calls and record.get("verdict") in VERDICTS:
            call = calls[record["choice_id"]]
            call["automated_grade"] = call["tool_choice_correctness"]
            call["tool_choice_correctness"] = record
    for audit in audits:
        if audit.get("choice_id") in calls and audit.get("verdict") in VERDICTS:
            call = calls[audit["choice_id"]]
            call.setdefault("prior_grade", call["tool_choice_correctness"])
            call.setdefault("human_audits", []).append(audit)
            call["tool_choice_correctness"] = {**audit, "provenance": "human-reviewed"}
    evidence["judge"] = {"status": grades.get("status", "not_run"), "wall_seconds": grades.get("wall_seconds"),
                         "usage": grades.get("usage"), "cost_scope": "judge_only_excluded_from_execution",
                         "limits": grades.get("limits"), "coverage": grades.get("coverage"),
                         "sampling": grades.get("sampling"), "selected_by_arm": dict(Counter(t.get("choice_id", "").split(":", 1)[0] for t in grades.get("trials", [])))}
    previous = []
    for path in sorted((run / "judge").glob("*/result.json")):
        if old_input and path.parent == old_input:
            continue
        attempt = read_json(path)
        previous.append({"status": attempt.get("status"), "wall_seconds": attempt.get("wall_seconds"), "usage": attempt.get("usage"),
                         "mode": attempt.get("evaluation_mode", "isolated_per_choice" if attempt.get("trials") else "legacy_batch_not_no_hindsight")})
    evidence["judge"]["prior_attempts"] = previous
    evidence["audit_errors"] = [x for x in [*fixture_errors, *audit_errors] if x != "missing_artifact"]


def _dimensions(arm, name):
    calls = [c for c in arm["calls"] if c["kind"] not in {"routing", "orchestration", "host_container"}]
    routing_calls = [c for c in calls if c["capability_ids"]]
    routing = _aggregate(c["routing"]["verdict"] for c in routing_calls) if name == "rippletide" else "ungradable"
    if name == "rippletide" and (arm["guard"]["errors"] or arm["guard"]["unobserved_host_containers"]) and routing == "correct":
        routing = "uncertain"
    return {"tool_choice_correctness": _aggregate(c["tool_choice_correctness"]["verdict"] for c in calls),
            "execution_success": _aggregate(c["execution_success"] for c in calls),
            "task_correctness": arm["task_correctness"]["verdict"], "routing_compliance": routing}


def share_view(evidence: dict) -> dict:
    """Allowlist export: free-text prompts, arguments, results and names never leak.

    Regex credential scrubbing alone cannot make arbitrary code or user text safe.
    Retain useful operation classes and ordinal tool aliases instead of snippets.
    """
    aliases = {}
    def label(call):
        kind = call["kind"]
        if kind in {"filename_search", "lexical_search", "mixed_search", "routing", "orchestration", "host_container", "command", "other"}:
            return kind.replace("_", " ")
        key = call["tool_name"] + str(call["arguments"].get("agent_type", ""))
        if key not in aliases:
            aliases[key] = f"{'information MCP' if kind == 'mcp' else 'specialist agent'} {len(aliases) + 1}"
        return aliases[key]
    exported = {"schema_version": 1, "title": "Paired routing evaluation", "redaction": "Arguments, results, prompts, credentials, paths, custom names and free-text judgments omitted by default.",
                "caveat": "One paired run is not a benchmark. Correct tool choice, successful execution, task checks and routing compliance are independent.",
                "judge": evidence["judge"], "arms": {}}
    for name, arm in evidence["arms"].items():
        counts = Counter(c["tool_choice_correctness"].get("provenance", "not_graded") for c in arm["calls"])
        rows = []
        eligible_calls = [c for c in arm["calls"] if c["kind"] not in {"routing", "host_container", "orchestration"}]
        choice_counts = Counter(c["tool_choice_correctness"]["verdict"] for c in eligible_calls)
        execution_counts = Counter(c["outcome"]["status"] for c in eligible_calls)
        for number, call in enumerate(arm["calls"], 1):
            routing = call["routing"]
            matched = next((d for d in arm["decisions"] if d["decision_id"] == routing.get("decision_id")), None)
            operation = (matched.get("request") or {}).get("operation") if matched else None
            operation = operation if operation in {"repository_search", "knowledge_lookup", "specialist_assignment"} else "unknown"
            rows.append({"step": number, "choice_id": "choice_" + digest(call["choice_id"])[:16], "tool": label(call), "context": operation,
                         "prior_observations": len(call["context_before"]), "covered": bool(call["capability_ids"]),
                         "decision": matched.get("status") if matched and matched.get("status") in {"selected", "defer"} else "unknown" if name == "rippletide" else "not_applicable",
                         "decision_source": matched.get("source") if matched and matched.get("source") in {"rule", "model", "fallback"} else "unknown",
                         "execution": call["outcome"]["status"], "tool_choice": call["tool_choice_correctness"]["verdict"],
                         "grade_provenance": call["tool_choice_correctness"]["provenance"], "routing": routing["status"]})
        decision_rows = []
        for index, decision in enumerate(arm["decisions"], 1):
            request = decision.get("request") or {}
            operation = request.get("operation")
            decision_rows.append({"decision": index, "operation": operation if operation in {"repository_search", "knowledge_lookup", "specialist_assignment"} else "unknown",
                                  "status": decision.get("status") if decision.get("status") in {"selected", "defer"} else "unknown",
                                  "source": decision.get("source") if decision.get("source") in {"model", "rule", "fallback"} else "unknown",
                                  "linked_call_count": len(decision["linked_call_ids"]),
                                  "execution": "see_linked_call_outcome" if decision["linked_call_ids"] else "unknown_no_linked_call"})
        exported["arms"][name] = {"status": arm["status"] if arm["status"] in {"setup-blocked", "running", "completed", "failed", "timed_out", "cancelled"} else "unknown",
                                  "wall_seconds": arm["wall_seconds"] if isinstance(arm["wall_seconds"], (int, float)) else None, "dimensions": arm["dimensions"],
                                  "tokens": arm["usage"]["tokens"], "usage_complete": arm["usage"]["complete"],
                                  "required_interventions": arm["interventions"]["required"], "intervention_ledger_complete": arm["interventions"]["complete"],
                                  "guard_present": arm["guard"]["present"], "guard_errors": arm["guard"]["errors"],
                                  "guard_blocked_attempts": arm["guard"]["blocked_attempts"], "missing_guard_proposals": arm["guard"]["missing_proposals"],
                                  "outside_registered_coverage": arm["guard"]["unsupported_or_outside_coverage"],
                                  "unobserved_host_containers": arm["guard"]["unobserved_host_containers"],
                                  "grade_provenance_counts": dict(counts), "timeline": rows,
                                  "tool_choice_counts": {v: choice_counts[v] for v in sorted(VERDICTS)},
                                  "execution_counts": {v: execution_counts[v] for v in ("success", "failure", "unknown")},
                                  "decisions": decision_rows, "routing_metrics": arm["routing_metrics"]}
        setup = arm["setup"]
        preflight_usage = setup.get("preflight_usage") or {}
        exported["arms"][name]["setup"] = {
            "preflight_wall_seconds": setup["preflight_wall_seconds"] if isinstance(setup["preflight_wall_seconds"], (int, float)) else None,
            "bootstrap_wall_seconds": setup["bootstrap_wall_seconds"] if isinstance(setup["bootstrap_wall_seconds"], (int, float)) else None,
            "preflight_tokens": numeric_usage(preflight_usage.get("tokens")), "preflight_usage_complete": preflight_usage.get("complete") is True,
            "scope": "setup_excluded_from_task_denominator"}
    # Judge usage is structured token metrics, not arbitrary judge stdout.
    judge_usage = evidence["judge"].get("usage") or {}
    exported["judge"] = {"status": evidence["judge"]["status"] if evidence["judge"]["status"] in {"completed", "partial", "failed", "timed_out", "not_run", "ungradable"} else "unknown",
                         "wall_seconds": evidence["judge"]["wall_seconds"] if isinstance(evidence["judge"]["wall_seconds"], (int, float)) else None,
                         "usage": {"tokens": numeric_usage(judge_usage.get("tokens")), "complete": judge_usage.get("complete") is True},
                         "limits": {k: v for k, v in (evidence["judge"].get("limits") or {}).items() if k in {"max_choices", "concurrency", "total_timeout_seconds"} and isinstance(v, (int, float))},
                         "coverage": {k: v for k, v in (evidence["judge"].get("coverage") or {}).items() if k in {"total_choices", "selected_choices", "graded_choices", "ungradable_choices"} and isinstance(v, int)},
                         "cost_scope": "judge_only_excluded_from_execution"}
    selected = evidence["judge"].get("selected_by_arm", {})
    exported["judge"]["selected_by_arm"] = {arm: selected.get(arm, 0) for arm in ("baseline", "rippletide")}
    sampling = evidence["judge"].get("sampling") or {}
    exported["judge"]["sampling"] = "balanced_registered_first_stratified" if sampling.get("method") == "balanced_arms_registered_first_native_mcp_agent_then_deterministic_random" else "legacy_exploratory_sample"
    exported["judge"]["unbalanced_sample"] = selected.get("baseline", 0) != selected.get("rippletide", 0)
    exported["judge"]["prior_attempts"] = [{"attempt": index + 1, "mode": "isolated_per_choice" if attempt.get("mode") == "isolated_per_choice" else "legacy_batch_not_no_hindsight",
                                            "wall_seconds": attempt.get("wall_seconds") if isinstance(attempt.get("wall_seconds"), (int, float)) else None,
                                            "tokens": numeric_usage((attempt.get("usage") or {}).get("tokens")),
                                            "usage_complete": (attempt.get("usage") or {}).get("complete") is True}
                                           for index, attempt in enumerate(evidence["judge"].get("prior_attempts", []))]
    return exported


def _markdown(value):
    lines = ["# Paired routing evaluation", "", value["caveat"], "", value["redaction"], "",
             "| Arm | Tool choice | Execution | Task checks | Routing | Wall seconds | Required interventions | Token coverage |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, arm in value["arms"].items():
        d = arm["dimensions"]
        lines.append(f"| {name} | {d['tool_choice_correctness']} | {d['execution_success']} | {d['task_correctness']} | {d['routing_compliance']} | {arm['wall_seconds']} | {arm['required_interventions'] if arm['required_interventions'] is not None else 'unknown'} | {'complete' if arm['usage_complete'] else 'incomplete'} |")
    for name, arm in value["arms"].items():
        lines += ["", f"## {name.capitalize()} timeline", "", "Tool calls are observed actions; decisions alone do not prove execution.", "",
                  f"Guard present: {arm['guard_present']}; errors: {arm['guard_errors']}; blocked attempts: {arm['guard_blocked_attempts']}; missing proposals: {arm['missing_guard_proposals']}; outside registered coverage: {arm['outside_registered_coverage']}.", "",
                  "| Step / audit ID | Context → decision | Tool | Outcome | Choice grade | Routing evidence |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for row in arm["timeline"]:
            lines.append(f"| {row['step']} / {row['choice_id']} | {row['context']} → {row['decision']} ({row['decision_source']}) | {row['tool']} | {row['execution']} | {row['tool_choice']} ({row['grade_provenance']}) | {row['routing']} |")
        lines += ["", "Token categories (subsets must not be added together):", "", "```json", json.dumps(arm["tokens"], indent=2), "```"]
        lines += ["", "Observed execution counts (a failed attempt can precede passing task checks): " + json.dumps(arm["execution_counts"]),
                  "Tool-choice labels (unknown/omitted choices are not passes): " + json.dumps(arm["tool_choice_counts"])]
        if arm["decisions"]:
            lines += ["", "Routing decisions (including recommendations with no verified execution):", "",
                      "| Decision | Context | Selection | Source | Linked calls | Execution |", "| --- | --- | --- | --- | --- | --- |"]
            for decision in arm["decisions"]:
                lines.append(f"| {decision['decision']} | {decision['operation']} | {decision['status']} | {decision['source']} | {decision['linked_call_count']} | {decision['execution']} |")
        lines += ["", "Routing-only measurements:", "", "```json", json.dumps(arm["routing_metrics"], indent=2), "```"]
        lines += ["", "Startup/preflight and bootstrap (excluded from task time/tokens):", "", "```json", json.dumps(arm["setup"], indent=2), "```"]
    lines += ["", "## Independent judge", "", "Automated judgments are provisional; human audits are append-only. Judge usage and time are excluded from task execution totals.", "", "```json", json.dumps(value["judge"], indent=2), "```", ""]
    return "\n".join(lines)


def report_pair(run: Path) -> dict:
    run = Path(run).resolve()
    evidence = build_pair_evidence(run)
    _apply_grades(run, evidence)
    for name, arm in evidence["arms"].items():
        arm["dimensions"] = _dimensions(arm, name)
    evidence["privacy"] = "Private evidence; use report.json/report.md/report.html for allowlist-redacted sharing."
    private_json(run / "evidence-private.json", evidence)
    shared = share_view(evidence)
    private_json(run / "report.json", shared)
    markdown = _markdown(shared)
    # No active code or remote resources; even compromised free text cannot execute.
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Paired routing evaluation</title><style>body{max-width:1100px;margin:2rem auto;padding:1rem;font:15px system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><body><pre>' + html.escape(markdown) + "</pre></body></html>"
    for name, content in (("report.md", markdown), ("report.html", page)):
        path = run / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    return shared
