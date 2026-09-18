from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .scenarios import expected_evidence
from .storage import append_event, digest, read_events, read_json, timestamp, write_json

ROLES = {"agent.reviewer": "rippletide_reviewer", "agent.test_specialist": "rippletide_test_specialist"}


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # Actual CLI raw MCP results carry a host timing header followed by
            # an Output section, while agent orchestration outputs are bare JSON.
            if value.startswith("Wall time:") and "\nOutput:\n" in value:
                try:
                    return json.loads(value.split("\nOutput:\n", 1)[1])
                except json.JSONDecodeError:
                    pass
            return None
    return value


def normalize_rollout(events: list[dict]) -> list[dict]:
    """Translate observed raw Codex function call/output pairs; never agent prose."""
    normalized = list(events)
    calls = {}
    last_usage = None
    for event in events:
        payload = event.get("payload", {})
        if event.get("type") == "session_meta" and payload.get("id"):
            normalized.append({"type": "thread.started", "thread_id": payload["id"]})
        if event.get("type") == "event_msg" and payload.get("type") == "token_count":
            last_usage = (payload.get("info") or {}).get("total_token_usage") or last_usage
        if event.get("type") != "response_item":
            continue
        if payload.get("type") == "function_call":
            arguments = _json_value(payload.get("arguments")) or {}
            namespace = payload.get("namespace", "")
            name = namespace + payload["name"] if namespace.startswith("mcp__") else payload["name"]
            calls[payload["call_id"]] = {"name": name, "arguments": arguments, "timestamp": event.get("timestamp")}
        elif payload.get("type") == "message" and payload.get("role") == "assistant":
            text = "\n".join(item.get("text", "") for item in payload.get("content", []) if item.get("type") == "output_text")
            if text:
                normalized.append({"type": "item.completed", "item": {"id": f"message-{len(normalized)}", "type": "agent_message", "text": text}})
        elif payload.get("type") == "function_call_output" and payload.get("call_id") in calls:
            call = calls[payload["call_id"]]
            name = call["name"].rsplit(".", 1)[-1]
            args = call["arguments"]
            output = _json_value(payload.get("output"))
            item = {"id": payload["call_id"], "arguments": args, "timestamp": call["timestamp"], "evidence_format": "raw_function_pair"}
            if name == "spawn_agent" and isinstance(output, dict) and output.get("agent_id"):
                item.update(type="collab_tool_call", tool="spawn_agent", agent_type=args.get("agent_type"), receiver_thread_ids=[output["agent_id"]], prompt=args.get("message", ""), status="completed")
            elif name in {"wait", "wait_agent", "close_agent"} and isinstance(output, dict):
                states = {}
                for agent_id, state in (output.get("status") or {}).items():
                    if isinstance(state, dict):
                        states[agent_id] = {"status": "completed" if "completed" in state else "unknown", "result": state.get("completed")}
                item.update(type="collab_tool_call", tool=name, agents_states=states, status="completed")
            elif name == "exec_command":
                output_text = str(payload.get("output", ""))
                code = output.get("exit_code") if isinstance(output, dict) else None
                if code is None:
                    match = re.search(r"Process exited with code (\d+)", output_text)
                    code = int(match.group(1)) if match else None
                item.update(type="command_execution", command=args.get("cmd", ""), exit_code=code, status="completed" if code is not None else "unknown", aggregated_output=output_text)
            elif call["name"].startswith("mcp__"):
                parts = call["name"].split("__", 2)
                item.update(type="mcp_tool_call", server=parts[1], tool=parts[2], result=output, status="completed" if output is not None else "unknown", error=bool(output.get("isError") or output.get("is_error")) if isinstance(output, dict) else None)
            else:
                continue
            normalized.append({"type": "item.completed", "item": item})
    if last_usage is not None and not any(event.get("type") == "turn.completed" for event in events):
        normalized.append({"type": "turn.completed", "usage": last_usage})
    return normalized


def session_summary(path: Path | None) -> dict:
    result = {"available": False, "thread_ids": [], "items": [], "usage": None, "agent_executions": [], "native_calls": [], "mcp_calls": [], "final_messages": []}
    if path is None or not path.is_file():
        return result
    events = normalize_rollout(read_events(path))
    result["available"] = True
    items = {}
    usages = []
    for event in events:
        if event.get("type") == "thread.started":
            result["thread_ids"].append(event["thread_id"])
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usages.append(event["usage"])
        if event.get("type") == "item.completed" and isinstance(event.get("item"), dict):
            item = event["item"]
            items[item.get("id", digest(item))] = item
    result["items"] = list(items.values())
    if usages:
        keys = set.intersection(*(set(usage) for usage in usages))
        result["usage"] = {key: sum(usage[key] for usage in usages) for key in keys if all(isinstance(usage[key], (int, float)) for usage in usages)}
    for item in result["items"]:
        if item.get("type") == "command_execution":
            result["native_calls"].append(item)
        elif item.get("type") == "mcp_tool_call":
            result["mcp_calls"].append(item)
        elif item.get("type") == "agent_message":
            result["final_messages"].append(item.get("text", ""))
    # Only structured host orchestration events qualify; agent prose is not proof.
    spawns = {}
    completed = set()
    for item in result["items"]:
        if item.get("type") != "collab_tool_call":
            continue
        tool = item.get("tool")
        arguments = item.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if tool == "spawn_agent":
            role = item.get("agent_type") or item.get("agent_role") or arguments.get("agent_type") or arguments.get("agent_role")
            for thread_id in item.get("receiver_thread_ids", []):
                spawns[thread_id] = {"role": role, "thread_id": thread_id, "spawn_call_id": item.get("id"), "timestamp": item.get("timestamp"), "prompt": item.get("prompt") or arguments.get("message", ""), "completed": False}
        for thread_id, state in item.get("agents_states", {}).items():
            if isinstance(state, dict) and state.get("status") == "completed":
                completed.add(thread_id)
    for thread_id, spawn in spawns.items():
        spawn["completed"] = thread_id in completed
        result["agent_executions"].append(spawn)
    return result


def verify_agents(run: Path, session_path: Path) -> dict:
    manifest = read_json(run / "run.json")
    evidence = session_summary(session_path)
    config_path = Path(manifest["workspace"]) / ".rippletide" / "config.json"
    config = read_json(config_path)
    verified = []
    expected = []
    for capability in config["capabilities"]:
        if capability["id"] not in ROLES:
            continue
        if capability["availability"].get("state") == "deliberately-disabled":
            continue
        role = ROLES[capability["id"]]
        expected.append(role)
        matches = [item for item in evidence["agent_executions"] if item["role"] == role and item["completed"]]
        if matches:
            capability["available"] = True
            capability["availability"] = {"status": "ready", "state": "verified", "checked_at": timestamp(), "evidence": str(session_path.resolve()), "thread_ids": [item["thread_id"] for item in matches]}
            verified.append(role)
    write_json(config_path, config)
    manifest["agent_preflight_session"] = str(session_path.resolve())
    write_json(run / "run.json", manifest)
    ready = bool(expected) and set(verified) == set(expected)
    return {"verified": verified, "expected": expected, "ready": ready, "reason": None if ready else "Every configured role must have structured real spawn and completion evidence; prose or an uncompleted spawn is insufficient."}


def decision_records(run: Path, *, include_preflight: bool = False) -> list[dict]:
    records = []
    for event in read_events(run / "router-events.jsonl"):
        if event.get("event") != "routing_decision":
            continue
        if event.get("phase") == "preflight" and not include_preflight:
            continue
        response = event.get("response", event)
        if not isinstance(response, dict) or "decision_id" not in response:
            continue
        records.append({**response, "timestamp": event.get("timestamp"), "envelope": event})
    return records


def call_after_decision(decision: dict, item: dict) -> bool:
    if not decision.get("timestamp") or not item.get("timestamp"):
        return False
    try:
        selected = datetime.fromisoformat(decision["timestamp"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        return started >= selected
    except (ValueError, TypeError):
        return False


def observed_target_matches(decision: dict, item: dict) -> bool:
    if not call_after_decision(decision, item):
        return False
    route = decision.get("route_id") or ""
    if route.startswith("native.") and item.get("type") == "command_execution":
        command = item.get("command", "")
        return item.get("exit_code") == 0 and "rg" in command and (("--files" in command) == (route == "native.filename_search"))
    if route.startswith("mcp.") and item.get("type") == "mcp_tool_call":
        invocation = decision.get("invocation") or {}
        return item.get("server") == invocation.get("server") and item.get("tool") == invocation.get("tool") and item.get("status") == "completed" and not item.get("error")
    if route in ROLES and item.get("type") == "collab_tool_call":
        args = item.get("arguments", {})
        role = item.get("agent_type") or item.get("agent_role") or (args.get("agent_type") if isinstance(args, dict) else None)
        return item.get("tool") == "spawn_agent" and role == ROLES[route]
    return False


def correlate(run: Path, session_path: Path, decision_id: str, call_id: str, note: str) -> dict:
    decisions = [item for item in decision_records(run) if item["decision_id"] == decision_id]
    session = session_summary(session_path)
    calls = [item for item in session["items"] if item.get("id") == call_id]
    if len(decisions) != 1 or len(calls) != 1 or not observed_target_matches(decisions[0], calls[0]):
        raise ValueError("Correlation requires one real decision and one successful matching host call in the specified session")
    if decisions[0].get("route_id") in ROLES and not any(item["spawn_call_id"] == call_id and item["completed"] for item in session["agent_executions"]):
        raise ValueError("Agent completion has not been observed")
    manifest = read_json(run / "run.json")
    return append_event(run / "correlations.jsonl", manifest["run_id"], "reviewed_correlation", decision_id=decision_id, call_id=call_id, session=str(session_path.resolve()), session_hash=digest(session_path.read_text()), note=note)


def report(run: Path, session_path: Path | None = None) -> dict:
    manifest = read_json(run / "run.json")
    path = session_path or (Path(manifest["session"]) if manifest.get("session") else None)
    session = session_summary(path)
    decisions = decision_records(run)
    events = [event for event in read_events(run / "tool-events.jsonl") if event.get("event") == "tool_call" and event.get("phase") == "task"]
    host_fixture_hashes = set()
    for item in session["mcp_calls"]:
        if item.get("status") != "completed" or item.get("error") or not isinstance(item.get("arguments"), dict):
            continue
        arguments = dict(item["arguments"])
        if item.get("tool") in {"search_documents", "search_issues"}:
            arguments.setdefault("limit", 5)
        arguments.setdefault("decision_id", None)
        host_fixture_hashes.add((item.get("server"), item.get("tool"), digest(arguments)))
    corroborated_events = [event for event in events if (event.get("server"), event.get("tool"), event.get("argument_hash")) in host_fixture_hashes]
    correlations = read_events(run / "correlations.jsonl")
    results = []
    model_categories = set()
    for decision in decisions:
        invocation = decision.get("invocation") or {}
        matching_host = [item for item in session["mcp_calls"] if observed_target_matches(decision, item) and isinstance(item.get("arguments"), dict) and item["arguments"].get("decision_id") == decision["decision_id"]]
        argument_hashes = set()
        for item in matching_host:
            arguments = dict(item["arguments"])
            if item["tool"] in {"search_documents", "search_issues"}:
                arguments.setdefault("limit", 5)
            arguments.setdefault("decision_id", None)
            argument_hashes.add(digest(arguments))
        direct = [event for event in events if event.get("decision_id") == decision["decision_id"] and event.get("status") == "success" and event.get("server") == invocation.get("server") and event.get("tool") == invocation.get("tool") and event.get("argument_hash") in argument_hashes]
        agent_matches = [item for item in session["agent_executions"] if item["completed"] and call_after_decision(decision, item) and item["role"] == ROLES.get(decision.get("route_id")) and decision["decision_id"] in item["prompt"]]
        reviewed = []
        for association in correlations:
            if association.get("decision_id") != decision["decision_id"] or path is None or association.get("session") != str(path.resolve()) or association.get("session_hash") != digest(path.read_text()):
                continue
            items = [item for item in session["items"] if item.get("id") == association.get("call_id")]
            if len(items) == 1 and observed_target_matches(decision, items[0]):
                reviewed.append(association)
        # One request can produce repeated calls, so multiple matches are not exact proof.
        executed = len(direct) == 1 or len(agent_matches) == 1 or len(reviewed) == 1
        category = (decision.get("route_id") or "").split(".")[0]
        if executed and decision.get("source") == "model":
            model_categories.add(category)
        results.append({"decision_id": decision["decision_id"], "route_id": decision.get("route_id"), "source": decision.get("source"), "status": decision.get("status"), "execution": "verified" if executed else "unknown", "evidence": direct or agent_matches or reviewed, "reason_code": decision.get("reason_code"), "elapsed_ms": decision.get("elapsed_ms")})
    ledger = read_events(run / "interventions.jsonl")
    counts = dict(Counter(event.get("category") for event in ledger))
    ledger_verified = bool(manifest.get("intervention_ledger_complete")) and session["available"]
    required = counts.get("required", 0) if ledger_verified else None
    grades = [read_json(path) for path in sorted(run.glob("acceptance-*.json"))]
    settings = read_json(Path(manifest["workspace"]) / ".rippletide" / "config.json")
    readiness = {entry["id"]: {"available": entry["available"], "availability": entry.get("availability")} for entry in settings["capabilities"]}
    observed_checks = {
        "native_execution": bool(session["native_calls"]) if session["available"] else None,
        "mcp_execution": any(event.get("status") == "success" for event in corroborated_events) if session["available"] else None,
        "agent_execution": any(item["completed"] for item in session["agent_executions"]) if session["available"] else None,
        "agent_test_specialist_completed": any(item["role"] == ROLES["agent.test_specialist"] and item["completed"] for item in session["agent_executions"]) if session["available"] else None,
        "agent_reviewer_completed": any(item["role"] == ROLES["agent.reviewer"] and item["completed"] for item in session["agent_executions"]) if session["available"] else None,
        "session_acceptance": any(grade["grader"] == "sessions" and grade["status"] == "passed" for grade in grades) if grades else None,
        "taskboard_starter": any(grade["grader"] == "taskboard" and grade.get("stage") == "starter" and grade["status"] == "passed" for grade in grades) if grades else None,
        "taskboard_filter": any(grade["grader"] == "taskboard" and grade.get("stage") == "filter" and grade["status"] == "passed" for grade in grades) if grades else None,
        "issue_SESSION-17": any("SESSION-17" in event.get("returned_record_ids", []) and event.get("status") == "success" for event in corroborated_events) if session["available"] else None,
    }
    check_results = {}
    required_evidence = expected_evidence(manifest)
    for name in required_evidence:
        if name in observed_checks:
            state = observed_checks[name]
            check_results[name] = "passed" if state is True else "failed" if state is False else "unknown"
        else:
            check_results[name] = manifest.get("manual_checks", {}).get(name, {}).get("status", "unknown")
    scenario_status = "passed" if check_results and all(value == "passed" for value in check_results.values()) else "failed" if "failed" in check_results.values() else "blocked" if "blocked" in check_results.values() else "unknown"
    successful = manifest.get("task_outcome") == "success" and scenario_status == "passed"
    if manifest["scenario_definition"]["grader"] != "evidence":
        successful = successful and any(grade["status"] == "passed" for grade in grades)
    if not session["available"]:
        successful = False
    usage_scope = "session"
    if manifest.get("secondary_workspace"):
        usage_scope = "primary_project_session_only"
    elif session["agent_executions"]:
        usage_scope = "parent_session_only"
    data = {
        "schema_version": 1, "run_id": manifest["run_id"], "scenario": manifest["scenario"], "variant": manifest["variant"], "task_outcome": manifest["task_outcome"],
        "application_acceptance": grades or "unknown", "decisions": results, "setup_decision_count": len(decision_records(run, include_preflight=True)) - len(decisions), "actual_fixture_calls": events,
        "native_call_count": len(session["native_calls"]) if session["available"] else None,
        "mcp_call_count": len(session["mcp_calls"]) if session["available"] else None,
        "agent_executions": session["agent_executions"] if session["available"] else "unknown",
        "qwen_execution_categories": sorted(model_categories), "qwen_category_requirement_met": model_categories == {"native", "mcp", "agent"},
        "usage": session["usage"], "usage_scope": usage_scope, "usage_complete_for_task": session["usage"] is not None and usage_scope == "session", "session_evidence": str(path) if session["available"] else None,
        "required_interventions": required, "interaction_counts": counts if ledger_verified else {"observed": counts, "completeness": "unknown"},
        "total_interactions": len(ledger) if ledger_verified else None,
        "successful_without_required_intervention": successful and required == 0 if ledger_verified else None,
        "manual_checks": manifest.get("manual_checks", {}), "required_scenario_evidence": required_evidence,
        "scenario_checks": check_results, "scenario_acceptance_status": scenario_status,
        "readiness": readiness, "baseline_has_no_routing": not decisions if manifest["variant"] == "A" else None,
        "limitations": ["Unmatched or ambiguous decisions stay unknown.", "Task completion and model-category evidence are separate from overall U01-U09 acceptance.", "A tester must review each scenario's required evidence and record any routing omissions or unplanned interventions."]
    }
    write_json(run / "report.json", data)
    return data


def compare(runs: list[Path]) -> dict:
    reports = [report(run) for run in runs]
    manifests = [read_json(run / "run.json") for run in runs]
    variants = {}
    normal_ids = {manifest["run_id"] for manifest in manifests if manifest["scenario_definition"].get("normal_cohort")}
    for variant in "ABCD":
        group = [entry for entry in reports if entry["variant"] == variant and entry["run_id"] in normal_ids]
        if not group:
            continue
        verified = all(entry["required_interventions"] is not None for entry in group)
        successes = sum(entry["successful_without_required_intervention"] is True for entry in group)
        rate = successes / len(group) if verified else None
        mean = sum(entry["required_interventions"] for entry in group) / len(group) if verified else None
        variants[variant] = {"attempts": len(group), "successful_zero_intervention_rate": rate, "mean_required_interventions": mean, "meets_90_percent": rate >= .9 if rate is not None else None, "meets_point2_mean": mean <= .2 if mean is not None else None, "usage_complete": all(entry["usage"] is not None and entry.get("usage_complete_for_task", False) for entry in group)}
    baseline = variants.get("A", {}).get("mean_required_interventions")
    for variant, result in variants.items():
        result["no_increase_over_A"] = result["mean_required_interventions"] <= baseline if result["mean_required_interventions"] is not None and baseline is not None else None
    snapshots = {manifest["source_snapshot_hash"] for manifest in manifests}
    return {"variants": variants, "excluded_non_normal_runs": [manifest["run_id"] for manifest in manifests if manifest["run_id"] not in normal_ids], "equivalent_application_snapshots": len(snapshots) == 1, "note": "Snapshot equivalence alone does not prove equivalent Codex settings. Missing evidence prevents autonomy claims; failed/stalled normal attempts remain in the denominator."}
