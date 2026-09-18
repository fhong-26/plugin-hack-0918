"""Deterministic local contracts; never mislabelled as official upstream scores."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import uuid

from jsonschema import Draft202012Validator

from rippletide_uat.storage import read_events, read_json, timestamp, write_json
from . import ADAPTER_VERSION, case_spec
from .service import Fixture, fingerprint, transport_name


def reference_match(call: dict, reference: dict, spec: dict) -> bool:
    name, accepted = next(iter(reference.items()))
    args = call["arguments"]
    schema = next(tool["parameters"] for tool in spec["tools"] if tool["name"] == name)
    return (call["tool"] == name and Draft202012Validator(schema).is_valid(args)
            and set(args) == set(accepted) and all(args[key] in values for key, values in accepted.items()))


def evaluate(case: str, events: list[dict], initial: dict, final: dict, response: str, *,
             completed: bool, proposals: list[dict], trace_complete: bool) -> dict:
    """Arguments/proposals are observed data; expected calls never enter prompts."""
    spec = case_spec(case)
    result = {"case": case, "status": "unknown", "checks": {}, "official_upstream_score": None,
              "grading_scope": "local_reference_calls" if case in {"B01", "B02", "B03"} else "local_milestone_contract",
              "adapter": ADAPTER_VERSION, "trace_complete": trace_complete,
              "tool_choice": "ungradable", "arguments": "ungradable"}
    if not completed or not trace_complete or not response.strip():
        result["reason"] = "Incomplete execution, final response or trace; silence is not abstention"
        return result
    calls = [event for event in events if event["phase"] == "task"]
    good = [event for event in calls if event["status"] == "success"]
    checks = result["checks"]
    if case in {"B01", "B02", "B03"}:
        expected = spec["oracle"]["reference_calls"]
        names = Counter(next(iter(ref)) for ref in expected)
        checks["tool_multiset"] = Counter(call["tool"] for call in calls) == names
        checks["proposal_multiset"] = Counter(call["tool"] for call in proposals) == names
        unmatched = list(expected)
        for call in calls:
            match = next((ref for ref in unmatched if reference_match(call, ref, spec)), None)
            if match is None:
                break
            unmatched.remove(match)
        checks["reference_arguments"] = not unmatched and len(calls) == len(expected) and all(any(reference_match(call, ref, spec) for ref in expected) for call in calls)
        checks["successful_execution"] = len(good) == len(calls)
        checks["unchanged_state"] = initial == final
        result["tool_choice"] = "correct" if checks["tool_multiset"] and checks["proposal_multiset"] else "incorrect"
        result["arguments"] = "correct" if checks["reference_arguments"] else "incorrect"
        if case == "B01":
            # A local fixture assertion, not BFCL weather ground truth.
            numbers = {float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", response)}
            checks["seeded_weather_values_in_response"] = {7.25, 18.5} <= numbers
        if case == "B03":
            # Intentionally narrow; this does not certify every prose claim.
            checks["city_labels_in_response"] = all(city in response.casefold() for city in ("boston", "rome"))
    elif case == "B04":
        clocks = [(i, event) for i, event in enumerate(good) if event["tool"] == "get_current_timestamp"]
        dependent = [(i, event) for i, event in enumerate(good) if event["tool"] == "search_reminder" and
                     any(j < i and abs(event["arguments"].get("reminder_timestamp_lowerbound", float("-inf")) - clock["result"]) <= 1 for j, clock in clocks)]
        checks["clock_before_dependent_search"] = bool(dependent)
        target = "Buy a nice rich navy bathing dress"
        checks["expected_reminder_retrieved"] = any(any(row["content"] == target for row in event["result"]) for _, event in dependent)
        checks["expected_content_in_response"] = target.casefold() in response.casefold()
        checks["unchanged_state"] = initial == final
        result["tool_choice"] = "correct" if checks["clock_before_dependent_search"] else "incorrect"
        result["arguments"] = result["tool_choice"]
    else:
        lookup = [i for i, event in enumerate(good) if event["tool"] == "search_contacts" and event["arguments"].get("name") == "Fredrik Thordendal"
                  and any(row["phone_number"] == "+12453344098" for row in event["result"])]
        enabled = [i for i, event in enumerate(good) if event["tool"] == "set_cellular_service_status" and event["arguments"] == {"on": True}]
        sends = [i for i, event in enumerate(good) if event["tool"] == "send_message_with_phone_number"]
        checks["prerequisite_graph"] = bool(sends and any(i < sends[0] for i in lookup) and any(i < sends[0] for i in enabled))
        messages = final["messages"]
        checks["exactly_one_message"] = len(messages) == len(initial["messages"]) + 1
        checks["recipient_content"] = checks["exactly_one_message"] and messages[-1]["recipient_phone_number"] == "+12453344098" and messages[-1]["content"].rstrip(".") == "How's the new album coming along"
        checks["no_unrelated_changes"] = all(initial[key] == final[key] for key in initial if key not in {"cellular", "messages"})
        checks["service_enabled"] = final["cellular"] is True
        checks["confirmation"] = "sent" in response.casefold() and "fredrik" in response.casefold()
        result["tool_choice"] = "correct" if checks["prerequisite_graph"] else "incorrect"
        result["arguments"] = "correct" if checks["recipient_content"] else "incorrect"
    result["status"] = "passed" if all(checks.values()) else "failed"
    result["execution_errors"] = sum(event["status"] != "success" for event in calls)
    result["extra_call_count"] = max(0, len(calls) - {"B01": 1, "B02": 0, "B03": 3, "B04": 2, "B05": 3}[case])
    return result


def final_response(arm: dict) -> str:
    path = arm.get("session_path")
    if not path or not Path(path).is_file():
        return ""
    events = read_events(Path(path))
    messages = [event["item"].get("text", "") for event in events if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
    return messages[-1] if messages and any(event.get("type") == "turn.completed" for event in events) else ""


def recommendation_grades(case: str, decisions: list[dict]) -> list[dict]:
    """Grade recommendations even when Codex never executes them."""
    spec = case_spec(case)
    expected = {"mcp.fixture." + next(iter(ref)) for ref in spec["oracle"].get("reference_calls", [])}
    result = []
    for decision in decisions:
        if (decision.get("request") or {}).get("operation") != "fixture_tool_use":
            continue
        verdict = "ungradable"
        if case in {"B01", "B02", "B03"} and decision.get("status") == "selected":
            verdict = "correct" if decision.get("route_id") in expected else "incorrect"
        elif case == "B02" and decision.get("source") == "model" and decision.get("reason_code") == "MODEL_DEFER":
            verdict = "correct"
        result.append({"decision_id": decision.get("decision_id"), "route_id": decision.get("route_id"),
                       "source": decision.get("source"), "reason_code": decision.get("reason_code"), "verdict": verdict,
                       "scope": "reference function membership or intentional model abstention; not argument/execution correctness"})
    return result


def grade_pair(run: Path) -> dict:
    from rippletide_uat.paired_evidence import build_pair_evidence
    from .runner import implementation_hash
    pair = read_json(run / "pair.json")
    case = pair["benchmark_case"]
    spec = case_spec(case)
    if read_json(run / "benchmark-source.json") != spec:
        raise ValueError("Frozen source/oracle differs from installed grader; use the matching version")
    if pair["benchmark_implementation_sha256"] != implementation_hash():
        raise ValueError("Fixture/grader code changed after preparation; retain this attempt and prepare a new one")
    evidence = build_pair_evidence(run)
    results, grades = {}, []
    for name, arm in pair["arms"].items():
        fixture = Fixture(run / name)
        events = fixture.events()
        initial = read_json(run / name / "fixture/initial-state.json")
        observed = evidence["arms"][name]
        task_calls = [call for call in observed["calls"] if any(identifier.startswith("mcp.fixture.") for identifier in call["capability_ids"])]
        mapping = {transport_name(tool["name"]): tool["name"] for tool in spec["tools"]}
        proposals = [{"tool": mapping[call["tool_name"].split("__", 2)[-1]], "arguments": call["arguments"]} for call in task_calls]
        hooks = [event for event in read_events(Path(arm["hook_events"])) if event.get("phase") == "task"] if Path(arm["hook_events"]).exists() else []
        trace_complete = bool(hooks and not observed["guard"]["errors"] and not observed["guard"]["missing_proposals"]
                              and not observed["guard"]["artifact_errors"] and not observed["guard"]["unobserved_host_containers"])
        proposed_hooks = [hook for hook in hooks if hook.get("event") == "tool_proposed" and hook.get("tool_name", "").startswith("mcp__benchmark_fixture__")]
        trace_complete &= len(proposed_hooks) == len(task_calls)
        completed_hooks = [hook for hook in hooks if hook.get("event") == "tool_completed" and hook.get("tool_name", "").startswith("mcp__benchmark_fixture__")]
        trace_complete &= len(completed_hooks) == len(events)
        session_events = read_events(Path(arm["session_path"])) if arm.get("session_path") else []
        trace_complete &= any(event.get("type") == "thread.started" and event.get("thread_id") for event in session_events)
        # Exact server-generated IDs, not temporal guessing, tie executions to host results.
        for event in events:
            matches = [hook for hook in hooks if hook.get("event") == "tool_completed"
                       and hook.get("tool_name") == "mcp__benchmark_fixture__" + transport_name(event["tool"])
                       and hook.get("tool_input") == event["arguments"]
                       and event["fixture_call_id"] in json.dumps(hook.get("tool_response"))]
            trace_complete &= len(matches) == 1
        trace_complete &= fingerprint(initial) == fixture.manifest["initial_state_sha256"] == arm["fixture_initial_state_sha256"]
        result = evaluate(case, events, initial, fixture.snapshot(), final_response(arm),
                          completed=arm["status"] == "completed", proposals=proposals, trace_complete=trace_complete)
        if result["status"] != "unknown":
            permitted = all(call["kind"] in {"routing", "host_container", "orchestration"} or call in task_calls for call in observed["calls"])
            result["checks"]["only_fixture_task_tools"] = permitted
            if not permitted:
                result.update(status="failed", tool_choice="incorrect")
        result.update(observed_calls=events, proposed_calls=proposals, final_response=final_response(arm),
                      routing=observed["routing_metrics"], wall_seconds=arm["wall_seconds"],
                      tokens=observed["usage"], interventions=observed["interventions"])
        recommendations = recommendation_grades(case, observed["decisions"])
        verdicts = [grade["verdict"] for grade in recommendations]
        result["recommendations"] = recommendations
        result["router_choice"] = ("not_applicable" if name == "baseline" else "incorrect" if "incorrect" in verdicts
                                    else "correct" if verdicts and all(verdict == "correct" for verdict in verdicts) else "ungradable")
        result["verified_model_selected_executions"] = sum(call["routing"].get("source") == "model" and
            call["routing"]["verdict"] == "correct" and call["routing"].get("status") == "authorized_selected" and
            call["outcome"]["status"] == "success" for call in task_calls) if trace_complete else None
        results[name] = result
        arm["benchmark_result"] = {key: result[key] for key in ("status", "checks", "tool_choice", "arguments", "grading_scope", "trace_complete", "official_upstream_score")}
        arm["acceptance"] = [check for check in arm["acceptance"] if check.get("check") != "benchmark_local_contract"]
        arm["acceptance"].append({"check": "benchmark_local_contract", "status": result["status"],
                                  "exit_code": 0 if result["status"] == "passed" else 1 if result["status"] == "failed" else None,
                                  "independence": "external", "phase": "acceptance"})
        arm["acceptance_status"] = result["status"]
        for call, proposal in zip(task_calls, proposals):
            verdict = "ungradable"
            if trace_complete and case in {"B01", "B02", "B03"}:
                verdict = "correct" if proposal["tool"] in {next(iter(ref)) for ref in spec["oracle"]["reference_calls"]} else "incorrect"
            grades.append({"choice_id": call["choice_id"], "verdict": verdict, "provenance": "fixture-approved",
                           "reason": "Local reference function membership only; arguments, multiplicity and absence are graded at case level",
                           "evidence": {"case": case, "entry_sha256": spec["source_entry_sha256"],
                                        "trace_sha256": fingerprint(events), "proposal_sha256": fingerprint(proposal)}})
    write_json(run / "pair.json", pair)
    document = {"schema_version": 1, "case": case, "generated_at": timestamp(), "results": results,
                "official_upstream_score": None, "adaptations": pair["benchmark_adaptations"]}
    archive = run / "benchmark-grades" / uuid.uuid4().hex
    archive.mkdir(parents=True, mode=0o700)
    write_json(archive / "results.json", document)
    write_json(archive / "choice-grades.json", grades)
    document["grade_archive"] = str(archive)
    write_json(run / "benchmark-results-private.json", document)
    (run / "benchmark-results-private.json").chmod(0o600)
    (run / "fixture-grades.jsonl").write_text("".join(json.dumps(grade) + "\n" for grade in grades))
    (run / "fixture-grades.jsonl").chmod(0o600)
    return document


def report(run: Path) -> dict:
    from rippletide_uat.paired_evidence import report_pair
    result = grade_pair(run)
    shared = report_pair(run)
    pair = read_json(run / "pair.json")
    spec = case_spec(result["case"])
    lines = [f"# {result['case']} experiment report", "", f"Run: {pair['run_id']}", "",
             f"Scenario: {spec['benchmark']} / `{spec['entry_id']}` at `{spec['revision']}`.", "",
             f"User request: {spec['prompt']}", "",
             "Available fixture tools: " + ", ".join(f"`{tool['name']}`" for tool in spec["tools"]) + ".", "",
             "Local adapted contracts, not official BFCL/ToolSandbox scores. Private raw evidence is retained separately.", "",
             "| Arm | Case checks | Executed/proposed tool choice | Router choice | Arguments | Seconds | Codex tokens | Required interventions |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, value in result["results"].items():
        metrics = shared["arms"][name]
        lines.append(f"| {name} | {value['status']} | {value['tool_choice']} | {value['router_choice']} | {value['arguments']} | {metrics['wall_seconds']} | {json.dumps(metrics['tokens'])} | {metrics['required_interventions']} |")
        lines.extend(["", f"{name} checks: `{json.dumps(value['checks'], sort_keys=True)}`", ""])
    lines += ["", "See [paired timelines](report.md) for routing, execution and coverage. Detailed requests, choices, call results and states are in `benchmark-results-private.json` and `evidence-private.json` (private).",
              "", "Failed/stalled attempts remain in the record. Unknown fields are not zero. A fast failed run is not a speed improvement.", ""]
    (run / "benchmark-report.md").write_text("\n".join(lines))
    (run / "benchmark-report.md").chmod(0o600)
    return result
