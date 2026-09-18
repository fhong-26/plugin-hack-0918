"""Synthetic parser/grader checks, not claims of live user-test success."""
import json
from pathlib import Path

import pytest

from rippletide_uat.correctness import Anonymizer, audit_grade, grade_pair, judge_cards, validate_grades, select_cards
from rippletide_uat.paired_evidence import build_pair_evidence, report_pair as public_report_pair
from rippletide_uat.storage import read_json, write_json
from rippletide_uat.trace_evidence import arm_traces, normalize_raw, session_usage, tool_kind, hook_calls, supplement_cli_outcomes


def report_pair(run):
    public_report_pair(run)
    return read_json(run / "evidence-private.json")


def log(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def raw(kind, payload, second=1):
    return {"type": kind, "timestamp": f"2026-09-18T12:00:{second:02d}Z", "payload": payload}


def meta(sid="parent", second=0, parent=None):
    return raw("session_meta", {"id": sid, "timestamp": f"2026-09-18T12:00:{second:02d}Z",
                                 "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent}}} if parent else "exec"}, second)


def turn(event, turn_id="t1", second=1):
    return raw("event_msg", {"type": event, "turn_id": turn_id}, second)


def usage(total, last, second=4):
    return raw("event_msg", {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": total, "output_tokens": total // 10, "cached_input_tokens": 0},
        "last_token_usage": {"input_tokens": last, "output_tokens": last // 10, "cached_input_tokens": 0}}}, second)


def call(name="exec_command", args=None, identity="call1", second=2):
    return raw("response_item", {"type": "function_call", "name": name, "arguments": json.dumps(args or {"cmd": "rg -n identity ."}), "call_id": identity}, second)


def output(value="Process exited with code 0\nOutput:\nidentity.py:12", identity="call1", second=3):
    return raw("response_item", {"type": "function_call_output", "call_id": identity, "output": value}, second)


def setup_pair(tmp_path, events=None):
    events = events or [meta(), turn("task_started"), call(), output(), usage(100, 100), turn("task_complete", second=5)]
    arms = {}
    for name in ("baseline", "rippletide"):
        log(tmp_path / name / "raw.jsonl", events)
        log(tmp_path / name / "hooks.jsonl", [])
        log(tmp_path / name / "router.jsonl", [])
        arms[name] = {"run_id": name, "workspace": str(tmp_path / name / "workspace"), "status": "completed",
                      "wall_seconds": 8, "parent_rollout": f"{name}/raw.jsonl", "session_path": None, "child_rollouts": [],
                      "hook_events": f"{name}/hooks.jsonl", "router_events": f"{name}/router.jsonl", "exit_code": 0,
                      "acceptance": [], "interventions": [], "settings": {}}
    pair = {"schema_version": 1, "run_id": "unit-pair", "repo": str(tmp_path / "private-repo"), "base": "main", "base_sha": "abc",
            "prompt": "Find the identity validation source", "mode": "paired", "router_model": "qwen25-rlcd",
            "profile": {"tools": {"capabilities": [], "preferences": {}}}, "arms": arms}
    write_json(tmp_path / "pair.json", pair)
    return pair


def good_hook(event="routing_authorized", decision="decision1", second=2, **extra):
    return {"event": event, "timestamp": f"2026-09-18T12:00:{second:02d}Z", "phase": "task", "session_id": "parent",
            "transcript_path": "/private/rollout-parent.jsonl", "turn_id": "t1", "call_id": "call1", "tool_name": "exec_command",
            "tool_input": {"cmd": "rg -n identity ."}, "decision_id": decision, "capability_id": "native.lexical_search", **extra}


def decision(second=1):
    return {"event": "routing_decision", "timestamp": f"2026-09-18T12:00:{second:02d}Z", "phase": "task",
            "request": {"goal": "Find identity", "operation": "repository_search"},
            "response": {"decision_id": "decision1", "status": "selected", "route_id": "native.lexical_search", "source": "model"}}


def test_four_dimensions_never_collapse_exit_zero_into_quality(tmp_path):
    setup_pair(tmp_path)
    result = report_pair(tmp_path)
    arm = result["arms"]["rippletide"]
    assert arm["dimensions"] == {"tool_choice_correctness": "ungradable", "execution_success": "correct", "task_correctness": "ungradable", "routing_compliance": "uncertain"}
    assert arm["interventions"]["required"] is None
    assert arm["guard"]["missing_proposals"] == 1
    assert result["arms"]["baseline"]["calls"][0]["tool_name"] == "exec_command"


def test_authorized_decision_call_and_execution_correlated(tmp_path):
    setup_pair(tmp_path)
    log(tmp_path / "rippletide/hooks.jsonl", [good_hook("tool_proposed"), good_hook()])
    log(tmp_path / "rippletide/router.jsonl", [decision()])
    report = report_pair(tmp_path)
    chosen = report["arms"]["rippletide"]["calls"][0]
    assert chosen["routing"]["verdict"] == "correct"
    assert chosen["routing"]["execution_observed"]
    assert report["arms"]["rippletide"]["decisions"][0]["linked_call_ids"] == [chosen["choice_id"]]


@pytest.mark.parametrize("fault", ["missing_decision", "older_call", "scope", "arguments", "turn", "duplicate"])
def test_incomplete_or_ambiguous_routing_never_passes(tmp_path, fault):
    setup_pair(tmp_path)
    auth = good_hook()
    if fault == "scope":
        auth.update(session_id="another", transcript_path="/tmp/another.jsonl")
    elif fault == "arguments":
        auth["tool_input"] = {"cmd": "rg other ."}
    elif fault == "turn":
        auth["turn_id"] = "another"
    log(tmp_path / "rippletide/hooks.jsonl", [auth, auth] if fault == "duplicate" else [auth])
    log(tmp_path / "rippletide/router.jsonl", [] if fault == "missing_decision" else [decision(9 if fault == "older_call" else 1)])
    assert report_pair(tmp_path)["arms"]["rippletide"]["dimensions"]["routing_compliance"] == "uncertain"


def test_guard_blocked_attempt_visible_not_claimed_as_execution(tmp_path):
    setup_pair(tmp_path, [meta(), turn("task_started"), call(), usage(100, 100), turn("task_complete", second=5)])
    log(tmp_path / "rippletide/hooks.jsonl", [good_hook("routing_blocked", reason_code="MISSING_ROUTING_DECISION")])
    result = report_pair(tmp_path)["arms"]["rippletide"]
    assert result["calls"][0]["execution_success"] == "ungradable"
    assert result["calls"][0]["routing"]["status"] == "blocked_attempt"
    assert result["guard"]["blocked_attempts"] == 1


def test_no_match_is_successful_search_not_failed_tool_choice(tmp_path):
    setup_pair(tmp_path, [meta(), turn("task_started"), call(), output("Process exited with code 1\nOutput:\n"), usage(100, 100), turn("task_complete", second=5)])
    chosen = report_pair(tmp_path)["arms"]["baseline"]["calls"][0]
    assert chosen["outcome"]["status"] == "success"
    assert chosen["tool_choice_correctness"]["verdict"] == "ungradable"


def test_task_acceptance_provenance_and_intervention_ledger(tmp_path):
    pair = setup_pair(tmp_path)
    pair["arms"]["baseline"]["acceptance"] = [{"status": "passed", "exit_code": 0, "independence": "external"}]
    pair["arms"]["rippletide"]["acceptance"] = [{"status": "passed", "exit_code": 0, "independence": "project_checks"}]
    pair["arms"]["baseline"]["interventions_complete"] = True
    write_json(tmp_path / "pair.json", pair)
    result = report_pair(tmp_path)
    assert result["arms"]["baseline"]["task_correctness"]["provenance"] == "independent-configured-checks"
    assert result["arms"]["rippletide"]["task_correctness"]["provenance"] == "project-checks-provisional"
    assert result["arms"]["baseline"]["interventions"]["required"] == 0
    assert result["arms"]["rippletide"]["interventions"]["required"] is None


def test_usage_replay_and_resume_cumulative_not_double_counted(tmp_path):
    events = [meta(), turn("task_started"), usage(100, 100), turn("task_complete", second=5),
              turn("task_started", "t2", 6), usage(150, 50, 7), turn("task_complete", "t2", 8)]
    pair = setup_pair(tmp_path, events + events)
    # Same session copied twice under different paths is still one bill.
    log(tmp_path / "copy.jsonl", events)
    pair["arms"]["baseline"]["child_rollouts"] = ["copy.jsonl"]
    trace = arm_traces(tmp_path, pair["arms"]["baseline"])
    assert trace["usage"]["tokens"]["input_tokens"] == 150
    assert trace["usage"]["complete"]
    assert len(trace["usage"]["sessions"]) == 1


def test_child_inherited_history_is_not_another_execution_or_bill(tmp_path):
    pair = setup_pair(tmp_path, [meta(), turn("task_started"), call("spawn_agent", {"agent_type": "reviewer"}),
                                 output('{"agent_id":"child"}'), usage(100, 100), turn("task_complete", second=5)])
    inherited = [call(second=2), output(second=3), usage(100, 100, 4)]
    child = [meta("child", 10, "parent"), *inherited, turn("task_started", "childturn", 11),
             call(identity="own-child-call", second=12), output(identity="own-child-call", second=13),
             usage(40, 40, 14), turn("task_complete", "childturn", 15)]
    log(tmp_path / "child.jsonl", child)
    pair["arms"]["baseline"]["child_rollouts"] = ["child.jsonl"]
    trace = arm_traces(tmp_path, pair["arms"]["baseline"])
    assert trace["usage"]["tokens"]["input_tokens"] == 140
    assert trace["usage"]["complete"]
    assert {c["call_id"] for c in trace["calls"]} == {"call1", "own-child-call"}
    pair["arms"]["baseline"]["child_rollouts"] = []
    missing = arm_traces(tmp_path, pair["arms"]["baseline"])
    assert not missing["usage"]["complete"]
    assert missing["usage"]["missing_child_sessions"] == ["child"]


def test_unknown_usage_base_and_missing_categories_stay_incomplete():
    session = normalize_raw([meta(), turn("task_started"), usage(200, 30), turn("task_complete", second=5)], "fallback")
    result = session_usage(session)
    assert result["usage"]["input_tokens"] == 30
    assert not result["complete"]
    assert "initial_usage_balance_unknown" in result["warnings"]
    empty = session_usage(normalize_raw([meta()], "fallback"))
    assert empty["usage"] is None and not empty["complete"]


def test_decision_cards_have_only_before_context_no_current_or_future_output(tmp_path):
    setup_pair(tmp_path, [meta(), turn("task_started"), call(identity="c1"), output("FIRST_OBSERVED", "c1"),
                          call(identity="c2", second=4), output("FUTURE_OUTCOME", "c2", 5), usage(100, 100, 6), turn("task_complete", second=7)])
    cards, identities = judge_cards(build_pair_evidence(tmp_path))
    first = [c for c in cards["decisions"] if identities[c["choice_id"]].endswith(":c1")]
    second = [c for c in cards["decisions"] if identities[c["choice_id"]].endswith(":c2")]
    assert all("FIRST_OBSERVED" not in str(c) and "FUTURE_OUTCOME" not in str(c) for c in first)
    assert all("FIRST_OBSERVED" in str(c) and "FUTURE_OUTCOME" not in str(c) for c in second)
    assert "baseline" not in json.dumps(cards) and "rippletide" not in json.dumps(cards)


def grade(card, acceptable=None, verdict="correct", arguments="correct", sufficient=True):
    return {"choice_id": card["choice_id"], "verdict": verdict, "acceptable_tools": acceptable or card["selected_tools"],
            "argument_verdict": arguments, "context_sufficient": sufficient, "reason": "Based on prior exact-symbol knowledge."}


def test_multiple_valid_tools_and_bad_arguments_are_separate(tmp_path):
    setup_pair(tmp_path)
    cards, identities = judge_cards(build_pair_evidence(tmp_path))
    first = cards["decisions"][0]
    acceptable = [entry["id"] for entry in cards["tool_catalog"]]
    values = validate_grades({"grades": [grade(first, acceptable, arguments="incorrect")]}, cards, identities)
    selected = next(v for v in values if v["choice_id"] == identities[first["choice_id"]])
    assert selected["verdict"] == "correct"
    assert selected["argument_verdict"] == "incorrect"
    assert any(v["verdict"] == "ungradable" for v in values)  # omitted choice
    uncertain = validate_grades({"grades": [grade(first, sufficient=False)]}, cards, identities)
    assert next(v for v in uncertain if v["choice_id"] == identities[first["choice_id"]])["verdict"] == "uncertain"


def test_missing_goal_cannot_pass_automated_grade(tmp_path):
    pair = setup_pair(tmp_path)
    pair["prompt"] = ""
    write_json(tmp_path / "pair.json", pair)
    cards, identities = judge_cards(build_pair_evidence(tmp_path))
    assert all(g["verdict"] == "ungradable" for g in validate_grades({"grades": [grade(c) for c in cards["decisions"]]}, cards, identities))


def test_judge_grade_does_not_change_execution_result_and_audit_is_append_only(tmp_path):
    setup_pair(tmp_path)
    cards, identities = judge_cards(build_pair_evidence(tmp_path))
    grades = validate_grades({"grades": [grade(c, verdict="incorrect") for c in cards["decisions"]]}, cards, identities)
    write_json(tmp_path / "correctness.json", {"status": "completed", "grades": grades})
    original = (tmp_path / "correctness.json").read_bytes()
    identity = grades[0]["choice_id"]
    audit_grade(tmp_path, identity, "correct", "The alternative source was valid given prior context.")
    audit_grade(tmp_path, identity, "uncertain", "Need an additional preference confirmation.")
    result = report_pair(tmp_path)
    chosen = next(c for a in result["arms"].values() for c in a["calls"] if c["choice_id"] == identity)
    assert chosen["execution_success"] == "correct"
    assert chosen["tool_choice_correctness"]["verdict"] == "uncertain"
    assert chosen["tool_choice_correctness"]["provenance"] == "human-reviewed"
    assert len(chosen["human_audits"]) == 2
    assert (tmp_path / "correctness.json").read_bytes() == original
    with pytest.raises(ValueError):
        audit_grade(tmp_path, "call1", "correct", "Ambiguous across both arms")


def test_share_exports_omit_sensitive_free_text_and_prevent_xss(tmp_path):
    secret = '<script>alert("secret")</script> sk-PRIVATE123 /Users/alice/private [link](https://evil.example/secret)'
    pair = setup_pair(tmp_path, [meta(), turn("task_started"), call(args={"cmd": "rg " + secret}), output(secret), usage(100, 100), turn("task_complete", second=5)])
    pair["prompt"] = secret
    pair["arms"]["baseline"]["wall_seconds"] = secret
    write_json(tmp_path / "pair.json", pair)
    report_pair(tmp_path)
    for file in ("report.json", "report.md", "report.html"):
        exported = (tmp_path / file).read_text()
        assert "PRIVATE123" not in exported and "alice" not in exported and "evil.example" not in exported
        assert "<script>" not in exported and 'alert("secret")' not in exported
    assert "PRIVATE123" in (tmp_path / "evidence-private.json").read_text()
    assert (tmp_path / "evidence-private.json").stat().st_mode & 0o777 == 0o600
    assert public_report_pair(tmp_path) == read_json(tmp_path / "report.json")


def test_anonymizer_credentials_paths_and_judge_rejects_unknown_tools():
    value = Anonymizer().text('Bearer SECRET api_key="SECRET" sk-PRIVATE /Users/alice/file alice@example.com https://name:password@example.com')
    assert "SECRET" not in value and "PRIVATE" not in value and "alice" not in value and "password@" not in value


def test_grade_invocation_separate_read_only_and_costs_separate(tmp_path, monkeypatch):
    setup_pair(tmp_path)
    from rippletide_uat import correctness
    def fake(command, **kwargs):
        assert command[:2] == ["codex-test", "exec"]
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert "--ignore-user-config" in command and "--ignore-rules" in command
        assert kwargs["environment"] == {"TEST_ENV": "isolated"}
        cards = read_json(kwargs["cwd"] / "input.json")
        assert len(cards["decisions"]) == 1
        write_json(Path(command[command.index("--output-last-message") + 1]), {"grades": [grade(c) for c in cards["decisions"]]})
        log(kwargs["stdout_path"], [{"type": "thread.started", "thread_id": "judge"}, {"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 2}}])
        return 0, False, 0.25
    monkeypatch.setattr(correctness, "_run_judge", fake)
    result = grade_pair(tmp_path, codex="codex-test", environment={"TEST_ENV": "isolated"})
    assert result["status"] == "completed" and result["usage"]["tokens"]["input_tokens"] == 18
    report = report_pair(tmp_path)
    assert report["arms"]["baseline"]["usage"]["tokens"]["input_tokens"] == 100
    assert report["judge"]["usage"]["tokens"]["input_tokens"] == 18


@pytest.mark.parametrize("command,kind", [("rg --files src", "filename_search"), ("grep identity f", "lexical_search"),
                                           ("find . -name '*.py'", "filename_search"), ("echo 'rg secret'", "command"),
                                           ("rg --files; rg -n token .", "mixed_search")])
def test_native_search_classification(command, kind):
    assert tool_kind("exec_command", {"cmd": command}) == kind


def test_modern_response_ids_exclude_cumulative_duplicates_and_foreign_usage():
    events = [meta(), turn("task_started")]
    for number, current, total in ((1, 20, 20), (2, 30, 50)):
        event = raw("token_usage_record", {"thread_id": "parent", "session_id": "parent", "response_id": f"r{number}",
                    "usage": {"input_tokens": current, "output_tokens": 2, "cache_write_input_tokens": current},
                    "thread_token_usage": {"input_tokens": total, "output_tokens": 2 * number, "cache_write_input_tokens": total}}, number + 1)
        events.extend([event, event, usage(total, current, number + 1)])
    events += [raw("token_usage_record", {"thread_id": "foreign", "response_id": "r9", "usage": {"input_tokens": 99999}}, 5), turn("task_complete", second=6)]
    result = session_usage(normalize_raw(events, "fallback"))
    assert result["usage"]["input_tokens"] == 50
    assert result["usage"]["cache_write_input_tokens"] == 50
    assert result["complete"] and result["basis"] == "unique_thread_response_ids"


def test_modern_task_name_agent_completed_from_scoped_child_metadata(tmp_path):
    pair = setup_pair(tmp_path, [meta(), turn("task_started"), call("spawn_agent", {"agent_type": "reviewer", "task_name": "review"}),
                                output('{"task_name":"/root/review"}'), usage(100, 100), turn("task_complete", second=5)])
    child_meta = meta("child", 10, "parent")
    child_meta["payload"].update(agent_path="/root/review", agent_role="reviewer", session_id="parent", parent_thread_id="parent")
    child = [child_meta, turn("task_started", "c", 11), usage(20, 20, 12), turn("task_complete", "c", 13)]
    log(tmp_path / "child.jsonl", child)
    pair["arms"]["baseline"]["child_rollouts"] = ["child.jsonl"]
    trace = arm_traces(tmp_path, pair["arms"]["baseline"])
    assert trace["calls"][0]["outcome"]["status"] == "success"
    assert trace["calls"][0]["outcome"]["child_id"] == "child"
    assert trace["usage"]["tokens"]["input_tokens"] == 120 and trace["usage"]["complete"]
    pair["arms"]["baseline"]["child_rollouts"] = []
    assert not arm_traces(tmp_path, pair["arms"]["baseline"])["usage"]["complete"]
    assert tool_kind("collaborationspawn_agent", {}) == "agent"


def test_nested_native_hook_tool_and_cli_exact_output_match(tmp_path):
    container = raw("response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "outer", "input": "OPAQUE_NOT_EXECUTED"}, 1)
    trace = {"sessions": [normalize_raw([meta(), turn("task_started"), container, output("result", "outer", 5)], "parent")]}
    trace["calls"] = trace["sessions"][0]["calls"]
    hook = good_hook("tool_proposed", second=2)
    hook.update(call_id="nested", tool_name="Bash", tool_input={"command": "rg --files"})
    hooks = [hook, {**hook, "event": "tool_completed", "timestamp": "2026-09-18T12:00:03Z", "tool_response": "sample.py\n"}]
    calls = hook_calls(trace, hooks)
    nested = next(c for c in calls if c["call_id"] == "nested")
    assert nested["kind"] == "filename_search" and nested["outcome"]["status"] == "unknown"
    log(tmp_path / "cli.jsonl", [{"type": "thread.started", "thread_id": "parent"}, {"type": "item.completed", "item": {
        "id": "item_1", "type": "command_execution", "command": "/bin/zsh -lc 'rg --files'", "exit_code": 0, "aggregated_output": "sample.py\n"}}])
    supplement_cli_outcomes(tmp_path, {"session_path": "cli.jsonl"}, calls)
    assert nested["outcome"]["status"] == "success"
    assert nested["outcome"]["evidence"] == "unique_exact_hook_cli_command_and_result"


def test_unlinked_router_decision_visible_and_model_costs_separate(tmp_path):
    setup_pair(tmp_path)
    event = decision()
    event["response"].update(elapsed_ms=12.0, input_tokens=80, output_tokens=0, readout_tokens=1)
    log(tmp_path / "rippletide/router.jsonl", [event])
    result = report_pair(tmp_path)
    metrics = result["arms"]["rippletide"]["routing_metrics"]
    assert metrics["unlinked_decision_count"] == 1
    assert metrics["small_model_tokens"] == {"input_tokens": 80, "output_tokens": 0, "readout_tokens": 1}
    assert "unknown_no_linked_call" in (tmp_path / "report.md").read_text()


def test_judge_tool_attempts_rejected(tmp_path, monkeypatch):
    setup_pair(tmp_path)
    from rippletide_uat import correctness
    def fake(command, **kwargs):
        cards = read_json(kwargs["cwd"] / "input.json")
        write_json(Path(command[command.index("--output-last-message") + 1]), {"grades": [grade(c) for c in cards["decisions"]]})
        log(kwargs["stdout_path"], [{"type": "thread.started", "thread_id": "judge"}, {"type": "item.completed", "item": {
            "id": "judge-read", "type": "command_execution", "command": "cat future.patch", "exit_code": 0, "aggregated_output": "future"}}])
        return 0, False, 0.1
    monkeypatch.setattr(correctness, "_run_judge", fake)
    result = grade_pair(tmp_path, codex="synthetic", environment={})
    assert result["status"] == "failed" and all(g["verdict"] == "ungradable" for g in result["grades"])
    assert all("invoked tools" in trial["error"] for trial in result["trials"])


def test_judge_cap_marks_omitted_calls_ungradable_without_cost(tmp_path, monkeypatch):
    setup_pair(tmp_path)
    from rippletide_uat import correctness
    def fake(command, **kwargs):
        cards = read_json(kwargs["cwd"] / "input.json")
        assert len(cards["decisions"]) == 1
        write_json(Path(command[command.index("--output-last-message") + 1]), {"grades": [grade(cards["decisions"][0])]})
        log(kwargs["stdout_path"], [{"type": "thread.started", "thread_id": "judge"}, {"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 2}}])
        return 0, False, 0.1
    monkeypatch.setattr(correctness, "_run_judge", fake)
    result = grade_pair(tmp_path, codex="synthetic", environment={"RIPPLETIDE_JUDGE_MAX_CHOICES": "1"})
    assert result["coverage"] == {"total_choices": 2, "selected_choices": 1, "graded_choices": 1, "ungradable_choices": 1}
    assert result["usage"]["tokens"]["input_tokens"] == 9
    assert len(result["trials"]) == 1


def test_judge_never_runs_during_task_phase(tmp_path):
    pair = setup_pair(tmp_path)
    pair["arms"]["rippletide"]["status"] = "running"
    write_json(tmp_path / "pair.json", pair)
    with pytest.raises(ValueError, match="still running"):
        grade_pair(tmp_path, codex="not-invoked", environment={})


def test_public_anonymous_choice_id_is_auditable(tmp_path):
    setup_pair(tmp_path)
    public = public_report_pair(tmp_path)
    choice = public["arms"]["baseline"]["timeline"][0]["choice_id"]
    record = audit_grade(tmp_path, choice, "correct", "Human checked the exact symbol intent.")
    assert record["choice_id"].startswith("baseline:")


def test_modern_child_retimestamped_parent_metadata_is_not_its_own_turn():
    child_meta = meta("child", 10, "parent")
    copied_parent = meta("parent", 0)
    copied_parent["timestamp"] = "2026-09-18T12:00:10Z"
    copied_start = turn("task_started", "parent-turn", 10)
    copied_start["payload"]["started_at"] = 1789732800
    # Use actual epoch values instead of relying on a guessed calendar conversion.
    from rippletide_uat.trace_evidence import instant
    copied_start["payload"]["started_at"] = int(instant(child_meta["timestamp"])) - 10
    own_start = turn("task_started", "child-turn", 11)
    own_start["payload"]["started_at"] = int(instant(child_meta["timestamp"]))
    record = raw("token_usage_record", {"thread_id": "child", "turn_id": "child-turn", "response_id": "response1",
                 "usage": {"input_tokens": 20}, "thread_token_usage": {"input_tokens": 20}}, 12)
    session = normalize_raw([child_meta, copied_parent, copied_start, own_start, record, turn("task_complete", "child-turn", 13)], "child")
    assert session_usage(session)["complete"]
    assert sum(e.get("type") == "session_meta" for e in session["events"]) == 1


def test_sampling_balances_arms_prioritizes_registered_and_stratifies_without_outcomes():
    evidence = {"run_id": "unit", "arms": {"baseline": {"calls": []}, "rippletide": {"calls": []}}}
    cards, identities = {"decisions": []}, {}
    for arm in evidence["arms"]:
        for index, category in enumerate(["native", "mcp", "agent", "native", "mcp", "mcp", "other", "other"]):
            public = f"{arm}-{index}"
            identity = f"{arm}:s:call{index}"
            identities[public] = identity
            cards["decisions"].append({"choice_id": public})
            evidence["arms"][arm]["calls"].append({"choice_id": identity, "capability_ids": [category + ".test"] if category != "other" else [], "outcome": {"status": "failure"}})
    selected, sampling = select_cards(cards, identities, evidence, 12)
    assert all(sampling["arms"][arm]["selected"] == 6 for arm in evidence["arms"])
    assert all(sampling["arms"][arm]["registered_selected"] == 6 for arm in evidence["arms"])
    for arm in evidence["arms"]:
        assert f"{arm}-2" in {x["choice_id"] for x in selected}
        for call in evidence["arms"][arm]["calls"]:
            call["outcome"]["status"] = "success"
    assert select_cards(cards, identities, evidence, 12)[0] == selected


def test_changed_context_invalidates_automated_grade_but_retains_original(tmp_path):
    pair = setup_pair(tmp_path)
    cards, identities = judge_cards(build_pair_evidence(tmp_path))
    grades = validate_grades({"grades": [grade(c) for c in cards["decisions"]]}, cards, identities)
    write_json(tmp_path / "correctness.json", {"status": "completed", "grades": grades})
    pair["prompt"] = "An entirely different task whose source requirements changed"
    write_json(tmp_path / "pair.json", pair)
    result = report_pair(tmp_path)
    for arm in result["arms"].values():
        assert arm["calls"][0]["tool_choice_correctness"]["verdict"] == "ungradable"
        assert arm["calls"][0]["tool_choice_correctness"]["original_verdict"] == "correct"


def test_setup_costs_are_separate_from_task_costs(tmp_path):
    pair = setup_pair(tmp_path)
    log(tmp_path / "preflight.jsonl", [meta("setup"), turn("task_started"), usage(50, 50), turn("task_complete", second=5)])
    pair["arms"]["baseline"]["preflight"] = {"wall_seconds": 2, "parent_rollout": "preflight.jsonl", "child_rollouts": []}
    pair["arms"]["baseline"]["bootstrap"] = [{"wall_seconds": 1}]
    write_json(tmp_path / "pair.json", pair)
    report = public_report_pair(tmp_path)
    baseline = report["arms"]["baseline"]
    assert baseline["tokens"]["input_tokens"] == 100
    assert baseline["setup"]["preflight_tokens"]["input_tokens"] == 50
    assert baseline["setup"]["bootstrap_wall_seconds"] == 1


def test_judge_failure_usage_counted_and_timeout_missing_usage_not_zero(tmp_path, monkeypatch):
    setup_pair(tmp_path)
    from rippletide_uat import correctness
    def fake(command, **kwargs):
        log(kwargs["stdout_path"], [{"type": "thread.started", "thread_id": "judge"}, {"type": "turn.completed", "usage": {"input_tokens": 17, "output_tokens": 3}}])
        return 1, False, 0.2
    monkeypatch.setattr(correctness, "_run_judge", fake)
    result = grade_pair(tmp_path, codex="synthetic", environment={"RIPPLETIDE_JUDGE_MAX_CHOICES": "1"})
    assert result["status"] == "failed"
    assert result["usage"]["tokens"]["input_tokens"] == 17
    def timeout(command, **kwargs):
        log(kwargs["stdout_path"], [{"type": "thread.started", "thread_id": "judge"}])
        return -15, True, 0.2
    monkeypatch.setattr(correctness, "_run_judge", timeout)
    result = grade_pair(tmp_path, codex="synthetic", environment={"RIPPLETIDE_JUDGE_MAX_CHOICES": "1"})
    assert result["trials"][0]["status"] == "timed_out"
    assert result["usage"]["tokens"] is None and not result["usage"]["complete"]


def test_cli_multiple_turns_without_counter_semantics_remain_unknown(tmp_path):
    log(tmp_path / "session.jsonl", [{"type": "thread.started", "thread_id": "parent"},
         {"type": "turn.completed", "usage": {"input_tokens": 100}}, {"type": "turn.completed", "usage": {"input_tokens": 150}}])
    result = arm_traces(tmp_path, {"session_path": "session.jsonl", "child_rollouts": []})
    assert result["usage"]["tokens"] is None and not result["usage"]["complete"]


def test_malformed_trace_stays_visible_and_incomplete(tmp_path):
    setup_pair(tmp_path)
    with (tmp_path / "baseline/raw.jsonl").open("a") as handle:
        handle.write('{"truncated":\n')
    report = report_pair(tmp_path)
    assert any("invalid_json_line" in warning for warning in report["arms"]["baseline"]["trace_warnings"])
    assert not report["arms"]["baseline"]["usage"]["complete"]
