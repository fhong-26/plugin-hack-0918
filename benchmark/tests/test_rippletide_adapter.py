"""No-inference regression tests for the full-context selector adapter."""
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
sys.path.insert(0, str(REPO / "plugins/rippletide/src"))
spec = importlib.util.spec_from_file_location("benchmark_rippletide_adapter", REPO / "benchmark/adapters/rippletide.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def task_input():
    return {"instruction": "Choose the next tool.", "context": ["Long context " * 2000, "é\nverbatim"],
            "host_instructions": ["Retain every host instruction."],
            "tools": [{"id": "mcp__example__search", "description": "Full description\n" * 2000},
                      {"id": "exec_command", "description": "Run a shell command"}]}


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from rippletide.selection import select_tool
        except ImportError as exc:
            raise unittest.SkipTest(f"Plugin dependencies unavailable: {exc}")

    def worker(self):
        worker = Mock()
        worker.start.return_value = True
        worker.status.return_value = {"ready": True, "startup_ms": 42}
        worker.predict.return_value = {"status": "selected", "route_id": "exec_command", "score": .8}
        return worker

    def assert_packet(self, worker, task):
        packet = worker.predict.call_args.args[0]
        self.assertEqual(json.loads(packet["context"]), {k: task[k] for k in
                                                      ("instruction", "context", "host_instructions")})
        self.assertEqual(packet["candidates"], task["tools"])
        self.assertEqual(worker.predict.call_args.kwargs["timeout"], 60)
        self.assertNotIn("facts", packet)  # Nested facts selected the old 1,024-token path.

    def test_large_input_reaches_full_context_worker_unchanged(self):
        task, worker = task_input(), self.worker()
        with patch.object(adapter.time, "perf_counter", side_effect=[10, 10.5]):
            result = adapter.choose(worker, task)
        self.assertEqual(result["tool_id"], "exec_command")
        self.assertEqual(result["elapsed_s"], .5)
        self.assertIsNone(result["error"])
        self.assert_packet(worker, task)

    def test_all_fifty_inputs_preserve_context_descriptions_and_order(self):
        for line in (REPO / "benchmark/data/tasks.jsonl").read_text().splitlines():
            case = json.loads(line)
            with self.subTest(case=case["id"]):
                worker = self.worker()
                result = adapter.choose(worker, case["input"])
                self.assertIsNone(result["error"])
                self.assert_packet(worker, case["input"])

    def test_actual_model_limit_error_remains_failure_without_fallback(self):
        worker = self.worker()
        worker.predict.return_value = {"status": "defer", "reason_code": "CONTEXT_TOO_LARGE"}
        result = adapter.choose(worker, task_input())
        self.assertIsNone(result["tool_id"])
        self.assertEqual(result["error"], "CONTEXT_TOO_LARGE")
        worker.predict.assert_called_once()

    def test_invalid_input_never_calls_worker(self):
        worker = self.worker()
        result = adapter.choose(worker, {})
        self.assertIsNone(result["tool_id"])
        self.assertIsNone(result["elapsed_s"])
        worker.predict.assert_not_called()

    def run_main(self, worker, text):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config.json").write_text('{"max_position_embeddings":32768}')
            with contextlib.redirect_stdout(output), patch.object(sys, "stdin", io.StringIO(text)), \
                    patch.object(sys, "argv", ["rippletide.py"]), \
                    patch("rippletide.model.WorkerManager", return_value=worker), \
                    patch("rippletide.artifacts.read_artifacts", return_value={"weights_path": directory}):
                status = adapter.main()
        return status, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_ready_reports_native_capacity_and_selector_deadline(self):
        worker = self.worker()
        status, messages = self.run_main(worker, json.dumps(task_input()) + "\n")
        self.assertEqual(status, 0)
        self.assertTrue(messages[0]["ready"])
        self.assertEqual(messages[0]["metadata"]["input_token_limit"], 32768)
        self.assertEqual(messages[0]["metadata"]["route_timeout_s"], 60)
        self.assertEqual(messages[1]["tool_id"], "exec_command")
        worker.start.assert_called_once_with(wait=True)
        worker.close.assert_called_once()

    def test_startup_failure_does_not_attempt_case(self):
        worker = self.worker()
        worker.start.return_value = False
        worker.status.return_value = {"error": "Missing artifacts"}
        status, messages = self.run_main(worker, json.dumps(task_input()) + "\n")
        self.assertEqual(status, 1)
        self.assertEqual(len(messages), 1)
        self.assertFalse(messages[0]["ready"])
        worker.predict.assert_not_called()
        worker.close.assert_called_once()

    def test_malformed_json_is_unmeasured_failure(self):
        worker = self.worker()
        status, messages = self.run_main(worker, "{bad\n")
        self.assertEqual(status, 0)
        self.assertIsNone(messages[1]["elapsed_s"])
        self.assertIn("JSONDecodeError", messages[1]["error"])
        worker.predict.assert_not_called()


if __name__ == "__main__":
    unittest.main()
