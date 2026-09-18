"""Adapter protocol tests; all router workers are mocked and download nothing."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("benchmark_rippletide_adapter", REPO / "benchmark/adapters/rippletide.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def task_input():
    return {"instruction": "Choose a tool.\nKeep the entire instruction.",
            "context": ["Context " * 1000, "é\nverbatim"],
            "host_instructions": ["Retain all host instructions."],
            "tools": [{"id": "mcp__example__search", "description": "Full description\nwith newlines"},
                      {"id": "exec_command", "description": "Run a shell command"}]}


class AdapterTests(unittest.TestCase):
    def test_preserves_input_and_excludes_registration_from_timing(self):
        task = task_input()
        router = Mock()
        router.route.return_value = {"status": "selected", "route_id": "exec_command"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def clock():
                self.assertTrue((root / ".rippletide/config.json").exists())
                return next(ticks)

            ticks = iter([10.0, 10.5])
            with patch.object(adapter.time, "perf_counter", side_effect=clock):
                result = adapter.choose(router, root, task)
            config = json.loads((root / ".rippletide/config.json").read_text())
        self.assertEqual(result["elapsed_s"], 0.5)
        self.assertEqual(result["tool_id"], "exec_command")
        self.assertIsNone(result["error"])
        self.assertTrue(config["fixture_mode"])
        self.assertEqual([{k: cap[k] for k in ("id", "description")} for cap in config["capabilities"]], task["tools"])
        request = router.route.call_args.kwargs
        self.assertEqual(request["goal"], task["instruction"])
        self.assertEqual(request["facts"], {k: task[k] for k in ("context", "host_instructions")})
        self.assertEqual([cap["kind"] for cap in config["capabilities"]], ["mcp", "native"])

    def test_defer_is_an_error_without_a_fallback(self):
        router = Mock()
        router.route.return_value = {"status": "defer", "route_id": None, "reason_code": "CONTEXT_TOO_LARGE"}
        with tempfile.TemporaryDirectory() as directory:
            result = adapter.choose(router, Path(directory), task_input())
        self.assertIsNone(result["tool_id"])
        self.assertEqual(result["error"], "CONTEXT_TOO_LARGE")
        self.assertEqual(result["cost_usd"], 0)
        router.route.assert_called_once()

    def test_invalid_input_does_not_call_router(self):
        router = Mock()
        with tempfile.TemporaryDirectory() as directory:
            result = adapter.choose(router, Path(directory), {})
        self.assertIsNone(result["tool_id"])
        self.assertEqual(result["elapsed_s"], 0)
        self.assertIn("KeyError", result["error"])
        router.route.assert_not_called()


class RouterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import the repository implementation, without installing or starting MLX.
        sys.path.insert(0, str(REPO / "plugins/rippletide/src"))
        try:
            from rippletide.router import Router
        except ImportError as exc:
            raise unittest.SkipTest(f"Optional plugin Python dependencies unavailable: {exc}")
        cls.Router = Router

    def run_main(self, worker, input_text):
        from rippletide import config
        original_preferences_path = config.global_preferences_path
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(sys, "stdin", io.StringIO(input_text)), \
                patch.object(sys, "argv", ["rippletide.py"]), \
                patch("rippletide.router.WorkerManager", return_value=worker):
            status = adapter.main()
        self.assertIs(config.global_preferences_path, original_preferences_path)
        return status, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_public_router_retains_full_context_and_sorts_candidates(self):
        worker = Mock()
        worker.start.return_value = True
        worker.status.return_value = {"ready": True, "startup_ms": 42}
        worker.predict.return_value = {"status": "selected", "route_id": "exec_command"}
        task = task_input()
        status, messages = self.run_main(worker, json.dumps(task) + "\n{malformed\n")
        self.assertEqual(status, 0)
        self.assertTrue(messages[0]["ready"])
        self.assertEqual(messages[0]["metadata"]["model_identity"]["model"], "qwen25-rlcd")
        self.assertEqual(messages[1]["tool_id"], "exec_command")
        self.assertIn("JSONDecodeError", messages[2]["error"])
        worker.start.assert_called_once_with(wait=True)
        worker.close.assert_called_once()
        packet = worker.predict.call_args.args[0]
        self.assertEqual(packet["facts"], {k: task[k] for k in ("context", "host_instructions")})
        self.assertEqual(packet["goal"], task["instruction"])
        self.assertEqual(packet["candidates"], [
            {**task["tools"][1], "kind": "native"}, {**task["tools"][0], "kind": "mcp"}])
        self.assertGreater(worker.predict.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(worker.predict.call_args.kwargs["timeout"], 2)

    def test_startup_failure_is_one_json_message(self):
        worker = Mock()
        worker.start.return_value = False
        worker.status.return_value = {"ready": False, "error": "Model artifacts missing"}
        status, messages = self.run_main(worker, json.dumps(task_input()) + "\n")
        self.assertEqual(status, 1)
        self.assertEqual(len(messages), 1)
        self.assertFalse(messages[0]["ready"])
        self.assertIn("Model artifacts missing", messages[0]["error"])
        worker.predict.assert_not_called()
        worker.close.assert_called_once()

    def test_saved_preferences_are_ignored_without_editing_them(self):
        worker = Mock()
        worker.start.return_value = True
        worker.status.return_value = {"ready": True, "startup_ms": 1}
        worker.predict.return_value = {"status": "selected", "route_id": "exec_command"}
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "preferences.json"
            original = json.dumps({"exclude": ["exec_command"],
                                   "prefer": {"benchmark_tool_selection": "mcp__example__search"}})
            saved.write_text(original)
            with patch("rippletide.config.global_preferences_path", return_value=saved):
                status, messages = self.run_main(worker, json.dumps(task_input()) + "\n")
            self.assertEqual(saved.read_text(), original)
        self.assertEqual(status, 0)
        self.assertEqual(messages[1]["tool_id"], "exec_command")
        worker.predict.assert_called_once()


if __name__ == "__main__":
    unittest.main()
