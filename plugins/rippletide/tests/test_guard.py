import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest


SPEC = importlib.util.spec_from_file_location("rippletide_guard", Path(__file__).parents[1] / "scripts" / "guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    config = {"capabilities": [
        {"id": "native.filename_search", "kind": "native", "available": True, "operations": ["repository_search"], "invocation": {}},
        {"id": "native.lexical_search", "kind": "native", "available": True, "operations": ["repository_search"], "invocation": {}},
        {"id": "mcp.docs_search", "kind": "mcp", "available": True, "operations": ["knowledge_lookup"], "invocation": {"server": "docs", "tool": "search"}},
        {"id": "agent.reviewer", "kind": "agent", "available": True, "operations": ["specialist_assignment"], "invocation": {"agent_type": "reviewer"}},
    ]}
    instance = guard.Guard(root, tmp_path / "run")
    return instance, root, config


def event(tool="Bash", call="execution", arguments=None, **changes):
    return {"hook_event_name": "PreToolUse", "session_id": "parent", "transcript_path": "/tmp/parent.jsonl", "turn_id": "turn",
            "tool_use_id": call, "tool_name": tool, "tool_input": arguments or {"command": "rg -n needle ."}, **changes}


def issue(case, route="native.lexical_search", operation="repository_search", decision="d1", **changes):
    instance, root, config = case
    request = event("mcp__rippletide__route", call=decision, arguments={"project_root": str(root), "goal": "find code", "operation": operation}, **changes)
    assert instance.handle(request, config) == {}
    response = {"decision_id": decision, "status": "selected" if route else "defer", "source": "model", "route_id": route}
    instance.handle({**request, "hook_event_name": "PostToolUse", "tool_response": {"content": [{"type": "text", "text": json.dumps(response)}]}}, config)


def blocked(response):
    return response.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def test_requires_single_use_and_matching_route(case):
    instance, _, config = case
    assert blocked(instance.handle(event(), config))
    issue(case)
    assert blocked(instance.handle(event(arguments={"command": "rg --files"}), config))
    assert instance.handle(event(), config) == {}
    assert blocked(instance.handle(event(call="second"), config))


def test_no_cross_turn_or_child_receipts(case):
    instance, _, config = case
    issue(case)
    assert blocked(instance.handle(event(turn_id="another"), config))
    assert blocked(instance.handle(event(transcript_path="/tmp/child.jsonl"), config))
    assert instance.handle(event(), config) == {}


def test_defer_is_one_operation_scoped_fallback(case):
    instance, _, config = case
    issue(case, route=None)
    assert blocked(instance.handle(event("mcp__docs__search", arguments={"query": "a"}), config))
    assert instance.handle(event(), config) == {}
    assert blocked(instance.handle(event(call="later"), config))
    entries = [json.loads(line) for line in instance.events.read_text().splitlines()]
    assert next(e for e in entries if e["event"] == "routing_authorized")["fallback"] is True


def test_new_decision_supersedes_abandoned_one(case):
    instance, _, config = case
    issue(case, decision="old")
    issue(case, decision="new")
    assert instance.handle(event(), config) == {}
    assert blocked(instance.handle(event(call="later"), config))


def test_mcp_and_agent_route_matching(case):
    instance, _, config = case
    issue(case, route="mcp.docs_search", operation="knowledge_lookup")
    assert instance.handle(event("mcp__plugin_docs__search", arguments={"query": "x"}), config) == {}
    issue(case, route="agent.reviewer", operation="specialist_assignment", decision="d2")
    assert instance.handle(event("spawn_agent", arguments={"agent_type": "reviewer", "message": "review"}), config) == {}
    issue(case, route="agent.reviewer", operation="specialist_assignment", decision="d3")
    assert instance.handle(event("collaborationspawn_agent", arguments={"agent_type": "reviewer", "task_name": "review", "message": "opaque"}), config) == {}


def test_fixture_receipts_require_explicit_mode_and_are_single_use(case):
    instance, _, config = case
    config["capabilities"] = [{"id": "mcp.fixture.clock", "kind": "mcp", "available": True,
                               "operations": ["fixture_tool_use"],
                               "invocation": {"server": "benchmark_fixture", "tool": "get_current_timestamp"}}]
    issue(case, route="mcp.fixture.clock", operation="fixture_tool_use")
    clock = event("mcp__benchmark_fixture__get_current_timestamp", arguments={})
    assert blocked(instance.handle(clock, config))
    config["fixture_mode"] = True
    issue(case, route="mcp.fixture.clock", operation="fixture_tool_use", decision="fixture")
    assert instance.handle(clock, config) == {}
    assert blocked(instance.handle({**clock, "tool_use_id": "again"}, config))


def test_concurrent_execution_claims_receipt_once(case):
    instance, _, config = case
    issue(case)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda i: instance.handle(event(call=str(i)), config), range(2)))
    assert sum(blocked(result) for result in results) == 1


def test_stale_and_unavailable_choices_block(case):
    instance, _, config = case
    issue(case)
    with instance.connect() as db:
        db.execute("UPDATE receipts SET issued=0")
    assert blocked(instance.handle(event(), config))
    issue(case, decision="fresh")
    config["capabilities"][1]["available"] = False
    assert blocked(instance.handle(event(), config))


def test_correction_exhaustion_is_visible(case):
    instance, _, config = case
    for _ in range(3):
        assert blocked(instance.handle(event(), config))
    entries = [json.loads(line) for line in instance.events.read_text().splitlines()]
    assert entries[-1]["exhausted"] is True


def test_observer_and_preflight_do_not_route(case):
    instance, _, config = case
    instance.mode = "observe"
    assert instance.handle(event(), config) == {}
    instance.mode, instance.phase = "enforce", "preflight"
    assert instance.handle(event(), config) == {}
    assert instance.handle(event("mcp__rippletide__status"), config) == {}


def test_observer_reads_frozen_registry_outside_baseline(tmp_path, case):
    instance, _, config = case
    (tmp_path / "task-registry.json").write_text(json.dumps(config))
    loaded = guard.observer_config(tmp_path, "task")
    assert loaded == config
    instance.mode = "observe"
    assert instance.handle(event(), loaded) == {}
    entries = [json.loads(line) for line in instance.events.read_text().splitlines()]
    assert entries[-1]["event"] == "tool_observed"
    assert entries[-1]["capability_ids"] == ["native.lexical_search"]
    assert guard.observer_config(tmp_path, "preflight") is None
    with pytest.raises(ValueError):
        guard.observer_config(tmp_path, "../task")


@pytest.mark.parametrize("command,expected", [
    ("rg --files | head", {"native.filename_search"}),
    ("zsh -lc 'rg -n needle src'", {"native.lexical_search"}),
    ("rg --files; rg -n needle .", {"native.filename_search", "native.lexical_search"}),
    ("cat known.py", set()), ("python -m pytest", set()),
    ("git grep needle", {"native.lexical_search"}),
    ("echo ready\nrg -n needle src", {"native.lexical_search"}),
    ("rg --files\nrg -n needle src", {"native.filename_search", "native.lexical_search"}),
    ("echo ready # comment\nrg -n needle src", {"native.lexical_search"}),
    ("# comment\nrg --files", {"native.filename_search"}),
    ("echo 'rg --files\nrg -n x .'", set()),
    ("echo '\n' rg -n x .", set()),
    ("echo '#'; rg --files", {"native.filename_search"}),
    ("echo foo#bar; rg --files", {"native.filename_search"}),
    ("echo ready # ; rg -n not-executed .", set()),
    ("rg \\\n--files", {"native.filename_search"}),
])
def test_explicit_shell_classification(command, expected):
    assert guard.shell_routes(command) == expected


def test_mixed_searches_cannot_consume_single_receipt(case):
    instance, _, config = case
    issue(case)
    assert blocked(instance.handle(event(arguments={"command": "rg --files; rg -n x ."}), config))
    assert blocked(instance.handle(event(arguments={"command": "rg --files\nrg -n x ."}), config))


def test_newline_search_after_bookkeeping_requires_a_receipt(case):
    instance, _, config = case
    assert blocked(instance.handle(event(arguments={"command": "echo ready\nrg -n needle src"}), config))


def test_heredoc_prose_is_uncovered_not_a_routing_error(case):
    instance, _, config = case
    command = "cat >> notes.md <<'EOF'\nThe user's notes.\nEOF"
    assert instance.handle(event(arguments={"command": command}), config) == {}
    entries = [json.loads(line) for line in instance.events.read_text().splitlines()]
    assert entries[-1]["event"] == "uncovered_tool"
    assert entries[-1]["reason_code"] == "UNSUPPORTED_SHELL_SYNTAX"
    assert not any(e["event"] in {"routing_authorized", "hook_error"} for e in entries)


def test_check_events_requires_real_agent_result(tmp_path):
    path = tmp_path / "events.jsonl"
    entries = []
    for tool, response in [("Bash", "rippletide-ready"), ("mcp__rippletide_uat_probe__ping", {"structuredContent": {"ready": True, "purpose": "host_hook_preflight"}, "isError": False}), ("spawn_agent", {"agent_id": "child"})]:
        for kind in ("tool_proposed", "tool_completed"):
            entries.append({"event": kind, "phase": "preflight", "session_id": "s", "transcript_path": "t", "call_id": tool, "tool_name": tool, "tool_response": response})
    path.write_text("\n".join(json.dumps(e) for e in entries))
    assert guard.check_events(path)["ready"]
    entries[-1]["tool_response"] = {"error": "no agent"}
    path.write_text("\n".join(json.dumps(e) for e in entries))
    assert not guard.check_events(path)["ready"]
    entries[-1]["tool_response"] = {"agent_id": "child"}
    entries[3]["tool_response"]["isError"] = True
    path.write_text("\n".join(json.dumps(e) for e in entries))
    assert not guard.check_events(path)["ready"]
    entries[3]["tool_response"]["isError"] = False
    entries[1]["tool_response"] = "command failed"
    path.write_text("\n".join(json.dumps(e) for e in entries))
    assert not guard.check_events(path)["ready"]
