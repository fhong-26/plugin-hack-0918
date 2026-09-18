"""Synthetic host-event samples test the parser only; these are not UAT passes."""

import json
import subprocess
import sys

import pytest

from rippletide_uat.evidence import correlate, report, session_summary, verify_agents
from rippletide_uat.prepare import prepare
from rippletide_uat.storage import append_event, digest, read_json, write_json


def write_session(path, events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events))


def test_missing_data_does_not_become_zero_or_agent_success(tmp_path):
    run = prepare("U02", "D", tmp_path, tmp_path / "plugin")
    result = report(run)
    assert result["usage"] is None
    assert result["required_interventions"] is None
    assert result["agent_executions"] == "unknown"
    assert not result["qwen_category_requirement_met"]
    assert result["scenario_acceptance_status"] == "unknown"


def test_agent_prose_or_spawn_without_completion_never_passes(tmp_path):
    run = prepare("U04", "D", tmp_path, tmp_path / "plugin")
    path = tmp_path / "unit-synthetic-session.jsonl"
    write_session(path, [{"type": "item.completed", "item": {"id": "p1", "type": "agent_message", "text": "I invoked rippletide_reviewer and it finished"}}, {"type": "item.completed", "item": {"id": "s1", "type": "collab_tool_call", "tool": "spawn_agent", "agent_type": "rippletide_reviewer", "receiver_thread_ids": ["child1"]}}])
    assert verify_agents(run, path)["verified"] == []
    assert not session_summary(path)["agent_executions"][0]["completed"]


def test_complete_named_host_agent_events_prove_readiness_only(tmp_path):
    run = prepare("U04", "D", tmp_path, tmp_path / "plugin")
    path = tmp_path / "unit-synthetic-session.jsonl"
    events = []
    for index, role in enumerate(("rippletide_reviewer", "rippletide_test_specialist")):
        thread = f"child{index}"
        events.extend([{"type": "item.completed", "item": {"id": f"s{index}", "type": "collab_tool_call", "tool": "spawn_agent", "agent_type": role, "receiver_thread_ids": [thread]}}, {"type": "item.completed", "item": {"id": f"w{index}", "type": "collab_tool_call", "tool": "wait_agent", "agents_states": {thread: {"status": "completed"}}}}])
    write_session(path, events)
    assert verify_agents(run, path)["ready"]
    assert report(run)["qwen_execution_categories"] == []


def test_native_correlation_requires_real_matching_host_call(tmp_path):
    run = prepare("U02", "D", tmp_path, tmp_path / "plugin")
    manifest = read_json(run / "run.json")
    append_event(run / "router-events.jsonl", manifest["run_id"], "routing_decision", timestamp="2026-01-01T00:00:00Z", response={"decision_id": "unit-decision", "status": "selected", "route_id": "native.lexical_search", "source": "model", "invocation": {"tool": "exec_command"}})
    session = tmp_path / "unit-synthetic-session.jsonl"
    write_session(session, [{"type": "item.completed", "item": {"id": "command1", "timestamp": "2026-01-01T00:00:01Z", "type": "command_execution", "command": "rg -n validate_identity .", "exit_code": 0, "status": "completed"}}, {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}])
    assert report(run, session)["decisions"][0]["execution"] == "unknown"
    with pytest.raises(ValueError):
        correlate(run, session, "unit-decision", "missing-call", "unit parser test")
    correlate(run, session, "unit-decision", "command1", "unit parser test")
    result = report(run, session)
    assert result["decisions"][0]["execution"] == "verified"
    assert result["qwen_execution_categories"] == ["native"]
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert result["required_interventions"] is None


def test_preflight_calls_are_not_task_execution(tmp_path):
    run = prepare("U02", "D", tmp_path, tmp_path / "plugin")
    result = report(run)
    assert result["actual_fixture_calls"] == []


def test_secondary_project_usage_is_not_claimed_complete(tmp_path):
    run = prepare("U06", "D", tmp_path, tmp_path / "plugin")
    path = tmp_path / "unit-primary-session.jsonl"
    write_session(path, [{"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}])
    result = report(run, path)
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert result["usage_scope"] == "primary_project_session_only"
    assert result["usage_complete_for_task"] is False


def test_raw_rollout_uses_call_arguments_and_completed_wait_not_prose(tmp_path):
    path = tmp_path / "unit-raw-rollout.jsonl"
    write_session(path, [
        {"type": "session_meta", "payload": {"id": "unit-thread"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "call_id": "spawn1", "arguments": json.dumps({"agent_type": "rippletide_reviewer", "message": "Review change; decision_id=unit-decision"})}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "spawn1", "output": json.dumps({"agent_id": "child1", "nickname": "Test"})}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "wait_agent", "call_id": "wait1", "arguments": json.dumps({"targets": ["child1"]})}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "wait1", "output": json.dumps({"status": {"child1": {"completed": "Observed review result"}}, "timed_out": False})}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 50, "output_tokens": 4}}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 8}}}},
    ])
    result = session_summary(path)
    assert result["agent_executions"] == [{"role": "rippletide_reviewer", "thread_id": "child1", "spawn_call_id": "spawn1", "timestamp": None, "prompt": "Review change; decision_id=unit-decision", "completed": True}]
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 8}


def test_fixture_event_alone_never_proves_Codex_execution(tmp_path):
    run = prepare("U03", "D", tmp_path, tmp_path / "plugin")
    run_id = read_json(run / "run.json")["run_id"]
    request = {"query": "expiration", "project": "session-alpha", "decision_id": "unit-mcp-choice"}
    append_event(run / "router-events.jsonl", run_id, "routing_decision", timestamp="2026-01-01T00:00:00Z", response={"decision_id": "unit-mcp-choice", "status": "selected", "source": "model", "route_id": "mcp.docs_search", "invocation": {"server": "uat_docs", "tool": "search_documents"}})
    append_event(run / "tool-events.jsonl", run_id, "tool_call", server="uat_docs", tool="search_documents", decision_id="unit-mcp-choice", status="success", phase="task", argument_hash=digest({**request, "limit": 5}), returned_record_ids=["DOC-SESSION-2"])
    assert report(run)["decisions"][0]["execution"] == "unknown"
    path = tmp_path / "unit-host.jsonl"
    write_session(path, [{"type": "item.completed", "item": {"id": "mcp1", "timestamp": "2026-01-01T00:00:01Z", "type": "mcp_tool_call", "server": "uat_docs", "tool": "search_documents", "arguments": request, "status": "completed", "error": None}}])
    assert report(run, path)["decisions"][0]["execution"] == "verified"


def test_namespaced_raw_MCP_with_host_timing_wrapper(tmp_path):
    path = tmp_path / "unit-mcp-raw.jsonl"
    write_session(path, [
        {"type": "response_item", "payload": {"type": "function_call", "namespace": "mcp__uat_docs__", "name": "search_documents", "call_id": "call1", "arguments": json.dumps({"query": "expiry", "project": "session-alpha"})}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call1", "output": 'Wall time: 0.0030 seconds\nOutput:\n{"records": []}'}}
    ])
    calls = session_summary(path)["mcp_calls"]
    assert len(calls) == 1
    assert calls[0]["server"] == "uat_docs" and calls[0]["tool"] == "search_documents"
    assert calls[0]["status"] == "completed" and not calls[0]["error"]


def test_correlation_rejects_execution_before_recommendation(tmp_path):
    run = prepare("U02", "D", tmp_path, tmp_path / "plugin")
    run_id = read_json(run / "run.json")["run_id"]
    append_event(run / "router-events.jsonl", run_id, "routing_decision", timestamp="2026-01-01T00:00:01Z", response={"decision_id": "too-late", "status": "selected", "route_id": "native.lexical_search", "source": "model"})
    path = tmp_path / "unit-earlier-command.jsonl"
    write_session(path, [{"type": "response_item", "timestamp": "2026-01-01T00:00:00Z", "payload": {"type": "function_call", "name": "exec_command", "call_id": "earlier-command", "arguments": json.dumps({"cmd": "rg -n validate_identity ."})}}, {"type": "response_item", "timestamp": "2026-01-01T00:00:02Z", "payload": {"type": "function_call_output", "call_id": "earlier-command", "output": "Process exited with code 0\nOutput:\nfound"}}])
    assert session_summary(path)["native_calls"][0]["timestamp"] == "2026-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        correlate(run, path, "too-late", "earlier-command", "Cannot retrospectively route an earlier execution")


def test_missing_live_targets_are_structured_blocked_without_external_calls():
    process = subprocess.run([sys.executable, "-m", "rippletide_uat", "live-readiness"], capture_output=True, text=True, timeout=10)
    result = json.loads(process.stdout)
    assert process.returncode == 1
    assert result["status"] == "blocked" and result["remote_actions_performed"] is False
    assert result["missing_prerequisites"] == ["linear_project_id", "notion_page_id"]


def test_null_route_fallback_survives_real_later_calls(tmp_path):
    run = prepare("U07", "D", tmp_path, tmp_path / "plugin", failure="model")
    run_id = read_json(run / "run.json")["run_id"]
    append_event(run / "router-events.jsonl", run_id, "routing_decision", timestamp="2026-01-01T00:00:00Z", response={"decision_id": "model-missing", "status": "defer", "route_id": None, "source": "fallback", "reason_code": "MODEL_NOT_READY"})
    path = tmp_path / "unit-fallback-session.jsonl"
    write_session(path, [{"type": "item.completed", "item": {"id": "fallback-search", "timestamp": "2026-01-01T00:00:01Z", "type": "mcp_tool_call", "server": "uat_docs", "tool": "search_documents", "arguments": {"query": "expiry", "project": "session-alpha", "decision_id": "model-missing"}, "status": "completed", "error": None}}])
    result = report(run, path)
    assert result["decisions"][0]["status"] == "defer"
    assert result["decisions"][0]["execution"] == "unknown"
    assert result["qwen_execution_categories"] == []


def test_explicit_preflight_routing_is_excluded_from_task_decisions(tmp_path):
    run = prepare("U02", "D", tmp_path, tmp_path / "plugin")
    run_id = read_json(run / "run.json")["run_id"]
    append_event(run / "router-events.jsonl", run_id, "routing_decision", phase="preflight", response={"decision_id": "setup-choice", "status": "selected", "route_id": "native.lexical_search", "source": "model"})
    result = report(run)
    assert result["decisions"] == []
    assert result["setup_decision_count"] == 1
    assert result["qwen_execution_categories"] == []
