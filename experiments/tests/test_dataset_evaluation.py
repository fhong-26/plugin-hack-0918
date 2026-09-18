import copy
import pytest

from personalization_lab.dataset import generate, training_history
from personalization_lab.evaluation import grade, summary, paired_delta, validation_gate


def test_split_families_domains_and_profiles_are_isolated():
    rows = generate()
    assert len(rows) == 360 and len({r["id"] for r in rows}) == len(rows)
    splits = {s: [r for r in rows if r["split"] == s] for s in ("train", "validation", "test")}
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        assert not {r["family_id"] for r in splits[left]} & {r["family_id"] for r in splits[right]}
        assert not {r["domain_id"] for r in splits[left]} & {r["domain_id"] for r in splits[right]}
    for row in rows:
        assert row["preferred_route"] in row["acceptable_routes"]
        assert not {"preferred_route", "acceptable_routes", "split", "user_id"} & row["packet"].keys()
    with pytest.raises(ValueError, match="training-history"):
        training_history(splits["test"], "developer_a")
    first = [r for r in rows if r["family_id"] == rows[0]["family_id"]]
    assert len({r["preferred_route"] for r in first}) == 2


def test_errors_never_count_as_correct_deferrals_and_pairs_require_same_cases():
    row = next(r for r in generate() if r["preferred_route"] == "defer")
    assert not grade(row, {"status": "defer", "reason_code": "MODEL_ERROR"})["preference_match"]
    assert grade(row, {"status": "defer", "reason_code": "MODEL_DEFER"})["preference_match"]
    with pytest.raises(ValueError, match="same nonempty"):
        paired_delta([], [])


def test_validation_gate_rejects_test_labels_and_objective_regressions():
    rows = [r for r in generate() if r["split"] == "validation"]
    before, after = [], []
    for row in rows:
        correct = {"status": "selected", "route_id": row["preferred_route"], "reason_code": "MODEL_SELECTION"}
        before.append(grade(row, {"status": "defer", "reason_code": "MODEL_DEFER"} if row["kind"] == "preference" else correct))
        after.append(grade(row, correct))
    assert validation_gate(before, after)["passed"]
    after[0]["split"] = "test"
    with pytest.raises(ValueError, match="final test"):
        validation_gate(before, after)
    after[0]["split"] = "validation"
    next(r for r in after if r["kind"] == "objective")["preference_match"] = False
    assert not validation_gate(before, after)["passed"]
