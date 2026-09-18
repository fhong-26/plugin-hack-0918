import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "pilot_summary", Path(__file__).resolve().parents[1] / "scripts" / "summarize_pilot.py"
)
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class CohortAccountingTests(unittest.TestCase):
    def test_failed_attempts_stay_in_denominator(self):
        result = summary.cohort([
            {"outcome": "success", "required_interventions": 0,
             "successful_without_required_intervention": True},
            {"outcome": "failed", "required_interventions": 1,
             "successful_without_required_intervention": False},
        ])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["zero_intervention_success_rate"], 0.5)
        self.assertEqual(result["mean_required_interventions"], 0.5)
        self.assertTrue(result["ledger_complete"])

    def test_missing_evidence_never_becomes_zero_interventions(self):
        result = summary.cohort([
            {"outcome": "success", "required_interventions": 0,
             "successful_without_required_intervention": True},
            {"outcome": "unknown", "required_interventions": None,
             "successful_without_required_intervention": None},
        ])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["zero_intervention_success_rate"], 0.5)
        self.assertIsNone(result["mean_required_interventions"])
        self.assertFalse(result["ledger_complete"])
        self.assertEqual(result["unreviewed_or_missing_reports"], 1)

    def test_empty_cohort_has_no_rates(self):
        result = summary.cohort([])
        self.assertEqual(result["attempts"], 0)
        self.assertIsNone(result["zero_intervention_success_rate"])
        self.assertIsNone(result["mean_required_interventions"])


if __name__ == "__main__":
    unittest.main()
