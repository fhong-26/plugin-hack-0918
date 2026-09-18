"""Opt-in real installed-plugin regression; retained evidence is never benchmark data."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pilot_driver", ROOT / "scripts" / "run_pilot.py")
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def json_values(value, depth=0):
    """Decode host tool output envelopes, never the assistant's account of them."""
    if depth > 12:
        return
    if isinstance(value, str):
        try:
            yield from json_values(json.loads(value), depth + 1)
        except ValueError:
            pass
    elif isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_values(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from json_values(child, depth + 1)


def same_call(left, right):
    fields = ("session_id", "transcript_path", "turn_id", "call_id")
    return all(left.get(key) and left[key] == right.get(key) for key in fields)


def parent_events(run, home):
    session = driver.read_events(run / "session.jsonl")
    thread = next(event["thread_id"] for event in session if event.get("type") == "thread.started")
    paths = list((home / "sessions").rglob(f"*{thread}*.jsonl"))
    if len(paths) != 1:
        raise AssertionError(f"Expected one parent rollout, found {len(paths)}: {run}")
    return thread, driver.read_events(paths[0])


def tool_outputs(raw):
    return [event["payload"].get("output") for event in raw
            if event.get("type") == "response_item"
            and event.get("payload", {}).get("type") in {"function_call_output", "custom_tool_call_output"}]


class EvidenceHelpers(unittest.TestCase):
    def test_only_actual_tool_outputs_can_prove_execution(self):
        successful = {"exit_code": 0, "output": "sample.py\n"}
        raw = [
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "output": successful}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "output": [{"type": "input_text", "text": json.dumps(successful)}]}},
        ]
        values = [value for output in tool_outputs(raw) for value in json_values(output) if "exit_code" in value]
        self.assertEqual(values, [successful])

    def test_call_correlation_requires_all_host_identity_fields(self):
        event = {"session_id": "s", "transcript_path": "t", "turn_id": "turn", "call_id": "c"}
        self.assertTrue(same_call(event, dict(event)))
        self.assertFalse(same_call(event, {**event, "call_id": "other"}))
        self.assertFalse(same_call(event, {**event, "transcript_path": None}))


@unittest.skipUnless(os.environ.get("RIPPLETIDE_HOST_INTEGRATION") == "1", "Opt-in real Codex session")
class InstalledHooks(unittest.TestCase):
    def test_missing_decision_reaches_real_host_denial(self):
        codex = ROOT / "tools" / "codex" / "node_modules" / ".bin" / "codex"
        output = ROOT / ".uat-runs"
        output.mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="hooks-denial-", dir=output))
        workspace, home = run / "workspace", run / "codex-home"
        workspace.mkdir()
        home.mkdir(mode=0o700)
        sentinel = workspace / "denial-sentinel.txt"
        command = "rg --files; printf '%s' executed > denial-sentinel.txt"
        profile = workspace / ".rippletide" / "config.json"
        profile.parent.mkdir()
        profile.write_text(json.dumps({"capabilities": [{"id": "native.filename_search", "kind": "native", "available": True,
                                                        "operations": ["repository_search"], "invocation": {}}]}))
        handler = {"type": "command", "command": f'python3 "{ROOT / "plugins/rippletide/scripts/guard.py"}"', "timeout": 5}
        # No routing skill/SessionStart instruction: independently test the host's
        # actual denial path, not whether the model obeys the normal skill.
        driver.write_user_config(home, {"plugins": {"rippletide@personal": {"enabled": False}},
                                       "features": {"hooks": True}, "approval_policy": "never",
                                       "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [handler]}]}})
        env = driver.isolated_environment(home)
        env.update(RIPPLETIDE_RUN_DIR=str(run), RIPPLETIDE_PHASE="task", RIPPLETIDE_PROJECT_ROOT=str(workspace), RIPPLETIDE_HOOK_MODE="enforce")
        link = driver.link_auth_if_needed(home)
        try:
            with (run / "session.jsonl").open("w") as stdout, (run / "stderr.log").open("w") as stderr:
                completed = subprocess.run([str(codex), "exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                                            "--dangerously-bypass-hook-trust", "-"], cwd=workspace, env=env, text=True,
                                           input=f"This is an authorized local hook verification. Invoke this exact shell command once in this directory: `{command}`. The sentinel is an intentional disposable test file. If a hook blocks the command, stop and report that. Do not retry, split the command, call Rippletide, create the sentinel separately, or use other tools.",
                                           stdout=stdout, stderr=stderr, timeout=90)
            self.assertEqual(completed.returncode, 0, str(run))
        finally:
            driver.remove_auth_link(link)
        events = [json.loads(line) for line in (run / "hook-events.jsonl").read_text().splitlines()]
        self.assertTrue(any(e["event"] == "routing_blocked" for e in events), str(run))
        self.assertFalse(any(e["event"] == "routing_authorized" for e in events), str(run))
        blocked = [e for e in events if e["event"] == "routing_blocked"]
        self.assertEqual(len(blocked), 1, str(run))
        self.assertEqual(blocked[0]["tool_input"]["command"], command, str(run))
        self.assertFalse(sentinel.exists(), f"The host executed a denied command: {run}")
        _, raw = parent_events(run, home)
        outputs = [json.dumps(value) for value in tool_outputs(raw)]
        self.assertTrue(any("blocked by PreToolUse hook" in value and command in value for value in outputs),
                        f"Guard emission alone is not evidence that the host enforced denial: {run}")
        (run / "result.json").write_text(json.dumps({"status": "passed", "kind": "host-denial-not-benchmark"}))

    def test_installed_native_mcp_agent_execute(self):
        codex = ROOT / "tools" / "codex" / "node_modules" / ".bin" / "codex"
        output = ROOT / ".uat-runs"
        output.mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="hooks-probe-", dir=output))
        workspace = run / "workspace"
        workspace.mkdir()
        (workspace / "sample.py").write_text("def example():\n    return True\n")
        home = run / "codex-home"
        home.mkdir(mode=0o700)
        data = run / "unavailable-model-data"
        data.mkdir()
        run.mkdir(exist_ok=True, mode=0o700)
        profile = workspace / ".rippletide" / "config.json"
        profile.parent.mkdir()
        capabilities = [
            {"id": "native.filename_search", "kind": "native", "available": True, "operations": ["repository_search"], "description": "Find source file paths", "invocation": {"tool": "exec_command", "command_hint": "rg --files"}, "input_schema": {"type": "object"}},
            {"id": "native.lexical_search", "kind": "native", "available": True, "operations": ["repository_search"], "description": "Find text in source files", "invocation": {"tool": "exec_command", "command_hint": "rg -n"}, "input_schema": {"type": "object"}},
            {"id": "agent.reviewer", "kind": "agent", "available": True, "operations": ["specialist_assignment"], "description": "A bounded read-only reviewer", "invocation": {"agent_type": "guard_probe"}, "input_schema": {"type": "object"}},
            {"id": "mcp.guard_probe", "kind": "mcp", "available": True, "operations": ["knowledge_lookup"], "description": "Retrieve a local service readiness record", "invocation": {"server": "rippletide_guard_probe", "tool": "ping"}, "input_schema": {"type": "object", "properties": {}}},
        ]
        profile.write_text(json.dumps({"version": 1, "registry_version": "guard-probe-v1", "run_id": run.name,
                                       "variant": "D", "log_path": str(run / "router-events.jsonl"),
                                       "preferences": {"exact_symbol_first": False}, "capabilities": capabilities}))
        agent_file = run / "agent.toml"
        agent_file.write_text('developer_instructions = "Reply PROBE_AGENT_OK to the assigned verification. Do not use tools, edit, or delegate."\n')
        config = {"plugins": {"rippletide@personal": {"enabled": True}},
                  "features": {"hooks": True, "multi_agent": True},
                  "agents": {"guard_probe": {"description": "Read-only integration verification", "config_file": str(agent_file)}},
                  "approval_policy": "never", "sandbox_mode": "read-only"}
        probe_python = ROOT / "user_tests/.venv/bin/python"
        self.assertTrue(probe_python.is_file(), "Run uv sync --locked --project user_tests first")
        config["mcp_servers"] = {"rippletide_guard_probe": {"command": str(probe_python),
            "args": ["-m", "rippletide_uat.probe_server"], "enabled_tools": ["ping"]}}
        driver.write_user_config(home, config)
        env = driver.isolated_environment(home)
        env.update(RIPPLETIDE_RUN_DIR=str(run), RIPPLETIDE_PHASE="task", RIPPLETIDE_PROJECT_ROOT=str(workspace),
                   RIPPLETIDE_DATA_DIR=str(data), RIPPLETIDE_HOOK_MODE="enforce")
        link = driver.link_auth_if_needed(home)
        prompt = f"""This is an authorized routing-guard integration test, not a coding task.
Stay within {workspace}. Call the installed Rippletide route tool with
project_root={workspace}, goal='Locate code that implements example behavior',
operation='repository_search', facts={{}}. Respect its selected tool, or on defer
run `rg --files` once. The model data is deliberately absent: that fallback is
expected. Next route a knowledge_lookup with the immediate goal 'Retrieve the
local probe service readiness record' and execute the selected
rippletide_guard_probe.ping MCP tool. Do not substitute router status for this
registered information call. Next route a bounded specialist_assignment to
the configured guard_probe reviewer and execute it, assigning: 'Reply
PROBE_AGENT_OK without tools, edits, or further delegation.' Wait for completion.
Return a short account of the native call, MCP call, and agent
completion. Do not edit files or change configuration. Do not inspect parent
directories, state databases, or plugin implementation. Stop after this sequence.
"""
        (run / "prompt.txt").write_text(prompt)
        try:
            installed = subprocess.run([str(codex), "plugin", "add", "rippletide@personal"],
                                       cwd=home, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            with (run / "session.jsonl").open("w") as stdout, (run / "stderr.log").open("w") as stderr:
                completed = subprocess.run([str(codex), "exec", "--json", "--sandbox", "read-only",
                                            "--skip-git-repo-check", "--dangerously-bypass-hook-trust", "-"],
                                           cwd=workspace, env=env, input=prompt, text=True,
                                           stdout=stdout, stderr=stderr, timeout=240)
            self.assertEqual(completed.returncode, 0, str(run))
        finally:
            driver.remove_auth_link(link)
        events = [json.loads(line) for line in (run / "hook-events.jsonl").read_text().splitlines()]
        blocked = [e for e in events if e["event"] == "routing_blocked"]
        authorized = [e for e in events if e["event"] == "routing_authorized"]
        thread, raw = parent_events(run, home)
        completions = {}
        for category, ids in {"native": {"native.filename_search", "native.lexical_search"},
                              "mcp": {"mcp.guard_probe"}, "agent": {"agent.reviewer"}}.items():
            matching = [event for event in authorized if event.get("capability_id") in ids]
            self.assertEqual(len(matching), 1, f"Expected one {category} authorization: {run}")
            receipt = matching[0]
            executed = [event for event in events if event["event"] == "tool_completed" and same_call(event, receipt)]
            self.assertEqual(len(executed), 1, f"Authorization is not completed {category} execution: {run}")
            completions[category] = executed[0]
        native = completions["native"]
        self.assertIn("sample.py", native["tool_response"], str(run))
        successful = [value for output in tool_outputs(raw) for value in json_values(output)
                      if value.get("exit_code") == 0 and value.get("output") == native["tool_response"]]
        self.assertEqual(len(successful), 1, f"Missing unique successful native host result: {run}")
        mcp = list(json_values(completions["mcp"]["tool_response"]))
        self.assertTrue(any(value.get("isError") is False for value in mcp), str(run))
        self.assertTrue(any(value.get("ready") is True and value.get("purpose") == "host_hook_preflight" for value in mcp), str(run))
        self.assertFalse(any(value.get("isError") is True or value.get("error") for value in mcp), str(run))
        spawned = next((value for value in json_values(completions["agent"]["tool_response"])
                        if value.get("agent_id") or value.get("task_name")), None)
        self.assertIsNotNone(spawned, str(run))
        children = []
        for path in (home / "sessions").rglob("*.jsonl"):
            child = driver.read_events(path)
            metadata = next((e.get("payload", {}) for e in child if e.get("type") == "session_meta"), {})
            if metadata.get("parent_thread_id") != thread or metadata.get("agent_role") != "guard_probe":
                continue
            if ((spawned.get("agent_id") and metadata.get("id") != spawned["agent_id"])
                    or (spawned.get("task_name") and metadata.get("agent_path") != spawned["task_name"])):
                continue
            finished = [e["payload"] for e in child if e.get("type") == "event_msg" and e.get("payload", {}).get("type") == "task_complete"]
            if any(item.get("last_agent_message", "").strip() == "PROBE_AGENT_OK" for item in finished):
                children.append(str(path))
        self.assertEqual(len(children), 1, f"Spawn acknowledgment is not verified child completion: {run}")
        (run / "result.json").write_text(json.dumps({"status": "passed", "kind": "integration-not-benchmark",
                                                      "blocked_calls": len(blocked), "authorized_calls": len(authorized),
                                                      "verified_completions": {key: value["call_id"] for key, value in completions.items()},
                                                      "child_rollout": children[0]}, indent=2))
        print(f"Installed hook evidence: {run}")


if __name__ == "__main__":
    unittest.main()
