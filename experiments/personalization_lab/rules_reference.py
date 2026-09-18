"""Supplemental diagnostic for the existing unconditional preference rules."""
from pathlib import Path

from rippletide.router import Router
from rippletide.personalization import atomic_json
from .dataset import read_rows, PROFILES
from .evaluation import grade, summary


def run_rules(dataset: Path, output: Path) -> dict:
    class NoModel:
        model = "qwen3-0.6b-torch"
        def predict(self, *args, **kwargs):
            raise AssertionError("Saved preference control must never call Qwen")
        def close(self):
            pass
    output.mkdir(parents=True, exist_ok=False)
    rows = read_rows(dataset, "test")
    grades = []
    for row in rows:
        root = output / row["id"]
        atomic_json(root / ".rippletide/config.json", {"variant": "C", "capabilities": row["registry"],
            "preferences": {"prefer": PROFILES[row["user_id"]]}})
        router = Router(worker=NoModel())
        result = router.route(project_root=str(root.resolve()), **{k: row["packet"][k]
            for k in ("goal", "operation", "facts", "recent_observations")})
        grades.append(grade(row, result))
    result = {"level": "supplemental unconditional saved-preference rule diagnostic",
        "added_after_main_run_started": True, "used_for_training_or_selection": False,
        "limitation": "Existing per-operation prefer rules are unconditional; the synthetic preferences are conditional on task suitability.",
        "summary": summary(grades), "grades": grades}
    atomic_json(output / "results.json", result)
    return result
