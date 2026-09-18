"""Exercise the actual adapter process using a fake app-server; no model calls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ADAPTER = Path(__file__).resolve().parents[1] / "adapters/codex.py"
SPEC = importlib.util.spec_from_file_location("codex_adapter", ADAPTER)
codex = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex)

FAKE = r'''
import json, os, sys, time, tomllib
from pathlib import Path
config = {"plugins": {"decision@fixture": {"enabled": True}}, "skills": None}
for index, value in enumerate(sys.argv):
    if value == "-c":
        key, value = sys.argv[index + 1].split("=", 1)
        data = config
        parts = key.split(".")
        for part in parts[:-1]:
            data = data.setdefault(part, {})
        data[parts[-1]] = tomllib.loads("v=" + value)["v"]
def emit(data):
    print(json.dumps(data), flush=True)
def event(method, params):
    emit({"method": method, "params": params})
thread_number = 0
mode = os.environ.get("FAKE_MODE", "ok")
for line in sys.stdin:
    request = json.loads(line)
    method, params = request.get("method"), request.get("params", {})
    if not method:
        continue
    with open(os.environ["FAKE_RECORD"], "a") as log:
        log.write(json.dumps(request) + "\n")
    result = {}
    if method == "initialize":
        result = {"userAgent": "fake-codex/1"}
    elif method == "config/read":
        result = {"config": config}
    elif method == "account/read":
        result = {"account": {"type": "apiKey"}}
    elif method == "thread/start":
        assert params["ephemeral"] and params["sandbox"] == "read-only"
        assert params["approvalPolicy"] == "never"
        assert params["allowProviderModelFallback"] is False
        assert "baseInstructions" not in params and "developerInstructions" not in params
        thread_number += 1
        result = {"thread": {"id": str(thread_number), "ephemeral": True, "cliVersion": "fake/1"},
                  "model": params["model"], "reasoningEffort": config["model_reasoning_effort"],
                  "serviceTier": "default", "approvalPolicy": "never", "sandbox": {"type": "readOnly"}}
    elif method == "mcpServerStatus/list":
        result = {"data": [{"name": "fixture", "pluginId": "tools@fixture", "tools": {},
                            "runtimeStatus": "disabled"}], "nextCursor": None}
        if mode == "mcp":
            result["data"][0]["runtimeStatus"] = "starting"
    elif method == "skills/list":
        result = {"data": []}
    elif method == "turn/start":
        assert config["plugins"]["decision@fixture"]["enabled"] is False
        thread_id = params["threadId"]
        turn_id = "turn-" + thread_id
        common = {"threadId": thread_id, "turnId": turn_id}
        emit({"id": request["id"], "result": {"turn": {"id": turn_id, "status": "inProgress"}}})
        event("item/completed", dict(common, item={"type": "reasoning", "content": ["PRIVATE_SENTINEL"]}))
        if mode == "timeout":
            time.sleep(5)
        if mode == "malformed":
            print("this is not json", flush=True)
            continue
        if mode == "tool":
            event("item/started", dict(common, item={"type": "mcpToolCall", "arguments": "PRIVATE_SENTINEL"}))
            continue
        if mode == "interactive":
            emit({"id": 900, "method": "item/tool/requestUserInput", "params": common})
            continue
        if mode == "reroute":
            event("model/rerouted", dict(common, fromModel="gpt-6-astra", toModel="another-model"))
            continue
        if mode == "error":
            event("error", dict(common, error={"message": "fixture service failure"}, willRetry=True))
            continue
        usage = {"inputTokens": 100, "cachedInputTokens": 20, "cacheWriteInputTokens": 30,
                 "outputTokens": 10, "reasoningOutputTokens": 7, "totalTokens": 110}
        if mode == "missing-cache":
            del usage["cacheWriteInputTokens"]
        event("thread/tokenUsage/updated", dict(common, tokenUsage={"total": usage, "last": usage}))
        case = json.loads(params["input"][0]["text"].split("CASE INPUT:\n", 1)[1])
        answer = "not-a-tool" if mode == "invalid" else case["tools"][0]["id"]
        event("item/completed", dict(common, item={"type": "agentMessage", "phase": "final_answer", "text": answer}))
        event("turn/completed", dict(common, turn={"id": turn_id, "status": "completed"}))
        continue
    if "id" in request:
        emit({"id": request["id"], "result": result})
'''


class CodexAdapterTest(unittest.TestCase):
    def run_adapter(self, mode="ok", *, check=False, model="gpt-6-astra", count=2):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            server = directory / "fake-codex"
            server.write_text("#!" + sys.executable + "\n" + textwrap.dedent(FAKE))
            server.chmod(0o700)
            # Persisted fake config is read-only throughout initialization.
            config = directory / "config.toml"
            config.write_text('[plugins."decision@fixture"]\nenabled=true\n')
            record = directory / "record.jsonl"
            case = '{ "instruction":"choose", "context":{"value":1}, "host_instructions":"host", "tools":[{"id":"test_tool","description":"full description"}] }'
            command = [sys.executable, str(ADAPTER), "--codex", str(server), "--model", model,
                       "--timeout", "0.5" if mode == "timeout" else "5"]
            if check:
                command.append("--check")
            env = dict(os.environ, CODEX_HOME=str(directory), FAKE_RECORD=str(record), FAKE_MODE=mode)
            result = subprocess.run(command, input=(case + "\n") * count, capture_output=True,
                                    text=True, timeout=15, env=env)
            requests = [json.loads(line) for line in record.read_text().splitlines()]
            rows = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertNotIn("PRIVATE_SENTINEL", result.stdout + result.stderr)
            self.assertEqual(config.read_text(), '[plugins."decision@fixture"]\nenabled=true\n')
            return result, rows, requests, case

    def test_full_input_fresh_threads_usage_and_cost(self):
        result, rows, requests, case = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(rows[0]["ready"])
        turns = [row["params"] for row in requests if row["method"] == "turn/start"]
        self.assertEqual(len({turn["threadId"] for turn in turns}), 2)
        wrapper = ADAPTER.with_name("wrapper.txt").read_text()
        self.assertTrue(all(turn["input"][0]["text"] == wrapper + case for turn in turns))
        for row in rows[1:]:
            self.assertEqual(row["tool_id"], "test_tool")
            self.assertIsNone(row["error"])
            self.assertGreaterEqual(row["elapsed_s"], 0)
            self.assertEqual(row["usage"]["uncachedInputTokens"], 50)
            self.assertAlmostEqual(row["cost_usd"], (50 * 10 + 20 + 30 * 12.5 + 10 * 50) / 1e6)

    def test_check_never_starts_a_turn(self):
        result, rows, requests, _ = self.run_adapter(check=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(rows), 1)
        self.assertFalse(any(row["method"] == "turn/start" for row in requests))

    def test_mcp_startup_fails_closed(self):
        result, rows, requests, _ = self.run_adapter("mcp")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(rows, [])
        self.assertFalse(any(row["method"] == "turn/start" for row in requests))

    def test_failure_stops_server_and_does_not_retry(self):
        for mode in ("tool", "interactive", "reroute", "error", "malformed", "timeout"):
            with self.subTest(mode=mode):
                result, rows, requests, _ = self.run_adapter(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sum(row["method"] == "turn/start" for row in requests), 1)
                self.assertTrue(rows[1]["fatal"])
                self.assertIsNotNone(rows[1]["elapsed_s"])
                self.assertIsNotNone(rows[1]["error"])
                self.assertIsNone(rows[1]["cost_usd"])
                self.assertIsNone(rows[2]["elapsed_s"])
                self.assertIsNone(rows[2]["tool_id"])

    def test_invalid_choice_is_error_not_abstention(self):
        result, rows, requests, _ = self.run_adapter("invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(row["method"] == "turn/start" for row in requests), 2)
        self.assertTrue(all(row["error"].startswith("ValueError: Invalid output") for row in rows[1:]))
        self.assertTrue(all(row["tool_id"] is None for row in rows[1:]))

    def test_unknown_cost_is_null(self):
        for options in ({"mode": "missing-cache"}, {"model": "other-model"}):
            with self.subTest(options=options):
                result, rows, _, _ = self.run_adapter(**options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(all(row["cost_usd"] is None for row in rows[1:]))

    def test_disjoint_cost_and_missing_counts(self):
        pricing = json.loads((ADAPTER.parents[1] / "pricing.json").read_text())
        usage = {"inputTokens": 10, "cachedInputTokens": 7, "cacheWriteInputTokens": 5, "outputTokens": 3}
        self.assertIsNone(codex.cost_for(usage, "gpt-6-astra", pricing))
        self.assertIsNone(codex.cost_for({}, "gpt-6-astra", pricing))


if __name__ == "__main__":
    unittest.main()
