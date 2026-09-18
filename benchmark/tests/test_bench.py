"""Offline checks: no model downloads, network calls, or paid inference."""
import asyncio
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bench", HERE / "bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.result = json.loads((HERE / "example/results.json").read_text())

    def test_recorded_run_reproduces_verified_metrics(self):
        systems, cases = bench.summarize(self.result)
        self.assertEqual([s["correct"] for s in systems], [30, 50])
        self.assertEqual(len(cases), 100)
        self.assertAlmostEqual(systems[0]["median_s"], 10.295143271010602)
        self.assertAlmostEqual(systems[1]["median_s"], 3.1820401044969913)
        self.assertAlmostEqual(systems[1]["total_cost_usd"], 10.7594125)

    def test_errors_count_wrong_without_changing_denominator(self):
        self.result["systems"][1]["predictions"][0]["error"] = "tool_attempt"
        systems, _ = bench.summarize(self.result)
        self.assertEqual((systems[1]["correct"], systems[1]["total"], systems[1]["invalid"]), (49, 50, 1))

    def test_missing_metrics_are_unknown_not_zero_or_partial(self):
        row = self.result["systems"][1]["predictions"][0]
        row.update(cost_usd=None, elapsed_s=None)
        systems, _ = bench.summarize(self.result)
        self.assertIsNone(systems[1]["total_cost_usd"])
        self.assertIsNone(systems[1]["median_s"])
        self.assertEqual(systems[1]["priced_cases"], 49)

    def test_missing_duplicate_and_out_of_order_cases_rejected(self):
        for change in (lambda p: p.pop(), lambda p: p.__setitem__(1, p[0]), lambda p: p.reverse()):
            result = copy.deepcopy(self.result)
            change(result["systems"][0]["predictions"])
            with self.assertRaises(ValueError):
                bench.summarize(result)

    def test_changed_benchmark_rejected(self):
        self.result["benchmark_sha256"] = "other"
        with self.assertRaises(ValueError):
            bench.summarize(self.result)

    def test_abstention_or_explanation_is_invalid(self):
        for value in ("ABSTAIN", "exec_command because it is best", "`exec_command`", [], {}):
            self.result["systems"][1]["predictions"][0]["tool_id"] = value
            systems, _ = bench.summarize(self.result)
            self.assertEqual(systems[1]["correct"], 49)

    def test_nonfinite_or_negative_metrics_rejected(self):
        for value in (float("nan"), float("inf"), -1, True):
            self.result["systems"][0]["predictions"][0]["elapsed_s"] = value
            with self.assertRaises(ValueError):
                bench.summarize(self.result)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, source, timeout=5):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            script = path / "chooser.py"
            script.write_text(source)
            cases = bench.tasks()[:3]
            return await bench.run_system("Fake", [sys.executable, "-u", str(script)], cases, path, timeout)

    async def test_adapter_receives_only_complete_unmodified_input(self):
        system = await self.invoke('''import json,sys
print(json.dumps({"ready":True,"metadata":{"test":True}}),flush=True)
for line in sys.stdin:
 p=json.loads(line)
 assert set(p)=={"instruction","context","host_instructions","tools"}
 assert all(set(t)=={"id","description"} for t in p["tools"])
 print(json.dumps({"tool_id":p["tools"][0]["id"],"elapsed_s":0.01,"cost_usd":0,"error":None,"seen":p}),flush=True)
''')
        for case, row in zip(bench.tasks(), system["predictions"]):
            self.assertEqual(row["response"]["seen"], case["input"])
            self.assertIsNone(row["error"])

    async def test_timeout_keeps_failed_and_unattempted_cases(self):
        system = await self.invoke('''import json,sys,time
print(json.dumps({"ready":True}),flush=True)
for line in sys.stdin:time.sleep(30)
''', timeout=.2)
        rows = system["predictions"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["error"].startswith("TimeoutError"))
        self.assertEqual(rows[1]["error"], "not_run_after_chooser_failure")
        self.assertIsNone(rows[1]["elapsed_s"])
        self.assertTrue(all(row["cost_usd"] is None for row in rows))

    async def test_invalid_json_is_retained_without_retry(self):
        system = await self.invoke('''import json,sys
print(json.dumps({"ready":True}),flush=True)
for line in sys.stdin:print("not JSON",flush=True)
''')
        self.assertTrue(system["predictions"][0]["error"].startswith("JSONDecodeError"))
        self.assertEqual(system["predictions"][2]["error"], "not_run_after_chooser_failure")

    async def test_non_string_tool_is_invalid_instead_of_crashing(self):
        system = await self.invoke('''import json,sys
print(json.dumps({"ready":True}),flush=True)
for line in sys.stdin:print(json.dumps({"tool_id":[],"elapsed_s":.1,"cost_usd":0}),flush=True)
''')
        self.assertTrue(all(row["error"] == "invalid_tool_id" for row in system["predictions"]))

    async def test_fatal_response_preserves_unknown_time_and_stops(self):
        system = await self.invoke('''import json,sys
print(json.dumps({"ready":True}),flush=True)
for line in sys.stdin:
 print(json.dumps({"tool_id":None,"elapsed_s":None,"cost_usd":None,"error":"server_dead","fatal":True}),flush=True)
''')
        rows = system["predictions"]
        self.assertEqual(rows[0]["error"], "server_dead")
        self.assertIsNone(rows[0]["elapsed_s"])
        self.assertEqual(rows[1]["error"], "not_run_after_chooser_failure")
        self.assertTrue(all(row["elapsed_s"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
