import tomllib
from pathlib import Path

import pytest

from rippletide_uat.graders import check_run
from rippletide_uat.prepare import prepare
from rippletide_uat.storage import read_json


@pytest.fixture
def create_run(tmp_path):
    def create(scenario="U02", variant="D", **kwargs):
        return prepare(scenario, variant, tmp_path / "runs", tmp_path / "plugin", **kwargs)
    return create


def test_prepare_enables_only_observed_dependencies_and_never_overwrites(create_run):
    run = create_run(run_id="one")
    config = read_json(run / "workspace" / ".rippletide" / "config.json")
    capabilities = {item["id"]: item for item in config["capabilities"]}
    assert capabilities["mcp.docs_search"]["available"]
    assert capabilities["mcp.tracker_search"]["available"]
    assert not capabilities["mcp.semantic_search"]["available"]
    assert not capabilities["agent.reviewer"]["available"]
    assert capabilities["agent.reviewer"]["availability"]["state"] == "configured-but-unverified"
    with pytest.raises(FileExistsError):
        create_run(run_id="one")
    with pytest.raises(ValueError):
        create_run(run_id="../escape")


def test_A_D_have_identical_application_sources_and_isolated_routing(create_run):
    a = create_run(variant="A")
    d = create_run(variant="D")
    assert read_json(a / "run.json")["source_snapshot_hash"] == read_json(d / "run.json")["source_snapshot_hash"]
    a_config = tomllib.loads((a / "workspace" / ".codex" / "config.toml").read_text())
    d_config = tomllib.loads((d / "workspace" / ".codex" / "config.toml").read_text())
    assert "rippletide" not in a_config["mcp_servers"]
    assert "rippletide" in d_config["mcp_servers"]
    assert not a_config["plugins"]["rippletide@personal"]["enabled"]


def test_independent_grader_rejects_bug_and_accepts_actual_fix(create_run):
    run = create_run()
    before = check_run(run)
    assert before["status"] == "failed"
    assert [check["name"] for check in before["checks"] if not check["passed"]] == ["exact_deadline"]
    source = run / "workspace" / "session_app" / "session_store.py"
    source.write_text(source.read_text().replace('now > session["expires_at"]', 'now >= session["expires_at"]'))
    assert check_run(run)["status"] == "passed"


def test_review_fixture_really_contains_a_regression(create_run):
    run = create_run("U04")
    from rippletide_uat.graders import grade_sessions
    result = grade_sessions(run / "workspace")
    assert [check["name"] for check in result["checks"] if not check["passed"]] == ["revoked"]


@pytest.mark.parametrize("scenario", ["U01", "U03", "U05", "U06", "U08", "U09"])
def test_all_other_scenarios_prepare_real_fresh_projects(create_run, scenario):
    run = create_run(scenario)
    manifest = read_json(run / "run.json")
    assert manifest["scenario"] == scenario
    assert (run / "prompt.txt").is_file()
    if scenario == "U01":
        assert not (run / "workspace" / "app.py").exists()
        assert check_run(run)["status"] == "failed"
    if scenario == "U06":
        first = read_json(run / "workspace" / ".rippletide" / "config.json")
        second = read_json(run / "workspace-secondary" / ".rippletide" / "config.json")
        assert first["preferences"] != second["preferences"]


@pytest.mark.parametrize("failure", ["docs", "tracker", "reviewer", "test_specialist", "model"])
def test_U07_prepares_explicit_dependency_failure(create_run, failure):
    run = create_run("U07", failure=failure)
    manifest = read_json(run / "run.json")
    assert manifest["failure"] == failure
    if failure in {"docs", "tracker"}:
        assert f"uat_{failure}" not in manifest["servers"]
    elif failure in {"reviewer", "test_specialist"}:
        assert not (run / "workspace" / ".codex" / "agents" / f"rippletide_{failure}.toml").exists()
    else:
        model_data = manifest["servers"]["rippletide"]["env"]["RIPPLETIDE_DATA_DIR"]
        assert model_data.startswith(str(run)) and not Path(model_data).exists()
