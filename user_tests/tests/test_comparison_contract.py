import json
import subprocess
import sys

import pytest

from rippletide_uat.evidence import report
from rippletide_uat.prepare import prepare, scenarios
from rippletide_uat.scenarios import expected_evidence
from rippletide_uat.storage import read_json, write_json


@pytest.mark.parametrize("base", ["U02", "U05"])
def test_new_U09_includes_base_and_comparison_checks(tmp_path, base):
    run = prepare("U09", "A", tmp_path, tmp_path / "plugin", comparison_scenario=base)
    manifest = read_json(run / "run.json")
    expected = list(dict.fromkeys(scenarios()[base]["evidence"] + scenarios()["U09"]["evidence"]))
    assert manifest["scenario_definition"]["evidence"] == expected
    assert expected_evidence(manifest) == expected
    result = report(run)
    assert set(result["scenario_checks"]) == set(expected)
    assert all(result["scenario_checks"][key] == "unknown" for key in scenarios()["U09"]["evidence"])


def test_older_U09_accepts_public_annotations_without_rewriting_evidence_contract(tmp_path):
    run = prepare("U02", "A", tmp_path, tmp_path / "plugin")
    manifest = read_json(run / "run.json")
    # Reproduce the earlier saved contract in this isolated unit fixture only.
    manifest.update(scenario="U09", comparison_scenario="U02")
    write_json(run / "run.json", manifest)
    before_evidence = list(manifest["scenario_definition"]["evidence"])
    required = expected_evidence(manifest)
    for key in scenarios()["U09"]["evidence"]:
        process = subprocess.run([sys.executable, "-m", "rippletide_uat", "record-check", "--run", str(run), "--name", key, "--status", "unknown", "--evidence", "Unit-test contract acceptance only; no outcome assertion"], capture_output=True, text=True, timeout=10)
        assert process.returncode == 0, process.stderr
        assert json.loads(process.stdout)["status"] == "unknown"
    after = read_json(run / "run.json")
    assert after["scenario_definition"]["evidence"] == before_evidence
    assert set(after["manual_checks"]) == set(scenarios()["U09"]["evidence"])
    result = report(run)
    assert result["required_scenario_evidence"] == required
    assert result["scenario_acceptance_status"] == "unknown"
    assert result["task_outcome"] == "unknown"
