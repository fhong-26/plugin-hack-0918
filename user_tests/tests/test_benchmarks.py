from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from rippletide_uat.benchmarks import CASE_IDS, case_spec, catalog
from rippletide_uat.benchmarks.grading import evaluate, recommendation_grades, report
from rippletide_uat.benchmarks.runner import prepare, tool_profile, verify_fixture_transport
from rippletide_uat.benchmarks.service import CLOCK, Fixture, initial_state, seed, transport_name
from rippletide_uat.profiles import validate_tool_config
from rippletide_uat.paired import _prepare_config, probe_capabilities
from rippletide_uat.storage import read_json, write_json


GOLDEN = {
    "B01": [("weather.get_by_coordinates_date", {"coordinates": [46.603354, 1.888334], "date": "2019-12-13"})],
    "B02": [],
    "B03": [("weather_forecast_temperature", {"location": "Boston, USA", "days": 10}),
            ("weather_forecast_humidity", {"location": "Boston, USA", "days": 10}),
            ("weather_forecast_precipitation", {"location": "Rome, Italy", "days": 10})],
    "B04": [("get_current_timestamp", {}), ("search_reminder", {"reminder_timestamp_lowerbound": CLOCK})],
    "B05": [("search_contacts", {"name": "Fredrik Thordendal"}), ("set_cellular_service_status", {"on": True}),
            ("send_message_with_phone_number", {"phone_number": "+12453344098", "content": "How's the new album coming along."})],
}
RESPONSES = {"B01": "7.25 °C, wind speed 18.5 km/h", "B02": "I have no bookstore lookup tool available.",
             "B03": "Boston temperature and humidity; Rome precipitation.", "B04": "Buy a nice rich navy bathing dress",
             "B05": "Sent your message to Fredrik Thordendal."}


def exercise(tmp_path, case, calls=None):
    seed(tmp_path, case)
    fixture = Fixture(tmp_path)
    calls = GOLDEN[case] if calls is None else calls
    for tool, args in calls:
        fixture.call(transport_name(tool), args)
    return fixture


def grade(case, fixture, **overrides):
    args = dict(events=fixture.events(), initial=initial_state(), final=fixture.snapshot(), response=RESPONSES[case], completed=True,
                trace_complete=True, proposals=[{"tool": event["tool"], "arguments": event["arguments"]} for event in fixture.events()])
    args.update(overrides)
    return evaluate(case, **args)


def test_catalog_contains_exact_pins_not_hidden_simulator_messages():
    assert set(catalog()["cases"]) == set(CASE_IDS)
    assert len(catalog()["sources"]) == 17
    assert all(len(value["sha256"]) == 64 for value in catalog()["sources"].values())
    assert set(catalog()["licenses"]) == {"BFCL", "ToolSandbox"}
    assert case_spec("B04")["prompt"] == "What's my upcoming reminder"
    assert "navy" not in case_spec("B04")["prompt"]
    assert case_spec("B01")["revision"] == "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
    assert case_spec("B05")["revision"] == "c8571d7854316d2e1c5f288e59fe1e34e53f6dd1"


@pytest.mark.parametrize("case", CASE_IDS)
def test_golden_local_contracts(tmp_path, case):
    result = grade(case, exercise(tmp_path, case))
    assert result["status"] == "passed", result
    assert result["official_upstream_score"] is None


@pytest.mark.parametrize("case", CASE_IDS)
@pytest.mark.parametrize("missing", ["completed", "trace_complete", "response"])
def test_missing_evidence_cannot_pass(tmp_path, case, missing):
    assert grade(case, exercise(tmp_path, case), **{missing: "" if missing == "response" else False})["status"] == "unknown"


def test_wrong_weather_choice_and_bad_arguments(tmp_path):
    wrong = exercise(tmp_path / "wrong", "B01", [("weather.get_forecast_by_coordinates", {"coordinates": [46.603354, 1.888334]})])
    assert grade("B01", wrong)["tool_choice"] == "incorrect"
    wrong_args = exercise(tmp_path / "args", "B01", [("weather.get_by_coordinates_date", {"coordinates": [46.603354, 1.888334], "date": "2020-01-01"})])
    assert wrong_args.events()[0]["result"] == []
    assert grade("B01", wrong_args)["arguments"] == "incorrect"
    assert grade("B01", exercise(tmp_path / "response", "B01"), response="It was 99 degrees")["status"] == "failed"


def test_irrelevance_blocks_are_not_abstention(tmp_path):
    fixture = exercise(tmp_path / "empty", "B02")
    assert grade("B02", fixture, proposals=[{"tool": "add_product_to_cart", "arguments": {"product_id": 1, "quantity": 1}}])["status"] == "failed"
    bad = exercise(tmp_path / "cart", "B02", [("add_product_to_cart", {"product_id": 1, "quantity": 1})])
    assert bad.snapshot()["cart"]
    assert grade("B02", bad)["status"] == "failed"


def test_router_choice_is_graded_even_when_it_is_not_executed():
    decision = {"decision_id": "choice", "request": {"operation": "fixture_tool_use"},
                "status": "selected", "route_id": "mcp.fixture.add_product_to_cart", "source": "rule", "reason_code": "ONLY_CANDIDATE"}
    assert recommendation_grades("B02", [decision])[0]["verdict"] == "incorrect"
    decision.update(status="defer", route_id=None, source="fallback", reason_code="ROUTER_TIMEOUT")
    assert recommendation_grades("B02", [decision])[0]["verdict"] == "ungradable"
    decision.update(source="model", reason_code="MODEL_DEFER")
    assert recommendation_grades("B02", [decision])[0]["verdict"] == "correct"


def test_three_calls_multiset_not_order(tmp_path):
    assert grade("B03", exercise(tmp_path / "reverse", "B03", list(reversed(GOLDEN["B03"]))))["status"] == "passed"
    for label, calls in (("missing", GOLDEN["B03"][:2]), ("duplicate", GOLDEN["B03"] + GOLDEN["B03"][:1])):
        assert grade("B03", exercise(tmp_path / label, "B03", calls))["status"] == "failed"
    wrong = copy.deepcopy(GOLDEN["B03"])
    wrong[0][1]["days"] = True
    fixture = exercise(tmp_path / "boolean", "B03", wrong)
    assert fixture.events()[0]["status"] == "error"
    assert grade("B03", fixture)["arguments"] == "incorrect"


def test_reminder_time_dependency(tmp_path):
    for label, calls in (("guessed", GOLDEN["B04"][1:]), ("reversed", list(reversed(GOLDEN["B04"]))),
                         ("wrong-bound", [("get_current_timestamp", {}), ("search_reminder", {"reminder_timestamp_lowerbound": CLOCK - 100})])):
        assert grade("B04", exercise(tmp_path / label, "B04", calls))["status"] == "failed"
    fixture = exercise(tmp_path / "tolerance", "B04", [("get_current_timestamp", {}), ("search_reminder", {"reminder_timestamp_lowerbound": CLOCK + 1})])
    assert grade("B04", fixture)["status"] == "passed"


def test_message_prerequisites_state_and_retry(tmp_path):
    fixture = exercise(tmp_path / "off", "B05", [GOLDEN["B05"][-1]])
    assert fixture.events()[0]["status"] == "error"
    assert fixture.snapshot()["messages"] == []
    assert grade("B05", fixture)["status"] == "failed"
    ordered = [GOLDEN["B05"][1], GOLDEN["B05"][0], GOLDEN["B05"][2]]
    assert grade("B05", exercise(tmp_path / "reverse", "B05", ordered))["status"] == "passed"
    recovered = exercise(tmp_path / "recovery", "B05", [GOLDEN["B05"][-1], *GOLDEN["B05"]])
    assert grade("B05", recovered)["status"] == "passed"
    assert grade("B05", recovered)["execution_errors"] == 1
    twice = exercise(tmp_path / "twice", "B05", GOLDEN["B05"] + GOLDEN["B05"][-1:])
    assert grade("B05", twice)["status"] == "failed"


def test_no_overwrite_or_cross_arm_mutation(tmp_path):
    left = exercise(tmp_path / "left", "B05")
    right = exercise(tmp_path / "right", "B05", [])
    assert left.snapshot()["messages"] and not right.snapshot()["messages"]
    with pytest.raises(FileExistsError):
        seed(tmp_path / "left", "B05")
    assert left.snapshot()["messages"]


@pytest.mark.parametrize("case", CASE_IDS)
def test_actual_stdio_catalog_and_execution(tmp_path, case):
    seed(tmp_path, case)
    async def run():
        config = tool_profile(case, tmp_path)["mcp_servers"]["benchmark_fixture"]
        async with Client(StdioServerParameters(command=config["command"], args=config["args"])) as client:
            listing = await client.list_tools()
            assert {tool.name for tool in listing.tools} == set(config["enabled_tools"])
            for name, args in GOLDEN[case]:
                result = await client.call_tool(transport_name(name), args)
                assert not result.is_error, result
                assert result.structured_content["fixture_call_id"]
            if case == "B02":
                assert listing.tools[0].annotations.read_only_hint is False
            if case == "B05":
                assert next(tool for tool in listing.tools if tool.name == "send_message_with_phone_number").annotations.read_only_hint is False
    asyncio.run(run())
    assert grade(case, Fixture(tmp_path))["status"] == "passed"


@pytest.mark.parametrize("case", CASE_IDS)
def test_prepare_isolation_and_equal_tool_configs(tmp_path, monkeypatch, case):
    monkeypatch.setenv("RIPPLETIDE_UAT_DATA_DIR", str(tmp_path / "profiles"))
    run, manifest = prepare(case, output_root=tmp_path / "runs")
    assert not manifest.get("task_started_at")
    baseline = _prepare_config("baseline", run, manifest, phase="task")
    enabled = _prepare_config("rippletide", run, manifest, phase="task")
    assert [tool for tool in baseline["mcp_servers"]["benchmark_fixture"]["enabled_tools"]] == enabled["mcp_servers"]["benchmark_fixture"]["enabled_tools"]
    assert not baseline["plugins"]["rippletide@personal"]["enabled"]
    for name, arm in manifest["arms"].items():
        workspace = Path(arm["workspace"])
        assert not list(workspace.rglob("catalog.json"))
        assert not list(workspace.rglob("*state.sqlite"))
        assert Fixture(run / name).snapshot() == initial_state()
    result = report(run)
    assert all(value["status"] == "unknown" for value in result["results"].values())


def test_local_mutation_exception_cannot_authorize_remote_or_arbitrary_command(tmp_path):
    for change in ({"url": "https://example.invalid/mcp"}, {"command": "/bin/sh", "args": ["-c", "touch forbidden"]}):
        config = tool_profile("B05")
        config["mcp_servers"]["benchmark_fixture"] = {**change, "enabled_tools": config["mcp_servers"]["benchmark_fixture"]["enabled_tools"]}
        with pytest.raises(ValueError, match="built-in"):
            validate_tool_config(config)
    seed(tmp_path, "B05")
    expected = tool_profile("B05", tmp_path)
    asyncio.run(probe_capabilities(expected["mcp_servers"], expected["capabilities"], {}, fixture_case="B05", fixture_run=tmp_path))
    with pytest.raises(ExceptionGroup) as error:
        asyncio.run(probe_capabilities(expected["mcp_servers"], expected["capabilities"], {}))
    def leaves(exc):
        return [leaf for child in exc.exceptions for leaf in leaves(child)] if isinstance(exc, BaseExceptionGroup) else [exc]
    assert any(isinstance(exc, ValueError) and "not read-only" in str(exc) for exc in leaves(error.value))
    with pytest.raises(ValueError, match="another command"):
        verify_fixture_transport({"bad": {"url": "https://example.invalid"}}, "B05", tmp_path)
    assert Fixture(tmp_path).events() == []  # tools/list does not execute mutations.


@pytest.mark.parametrize("case", CASE_IDS)
def test_report_correlates_fixture_ids_and_preserves_grading_attempts(tmp_path, monkeypatch, case):
    """Synthetic host transcripts test the harness, never count as Codex evidence."""
    monkeypatch.setenv("RIPPLETIDE_UAT_DATA_DIR", str(tmp_path / "profiles"))
    run, pair = prepare(case, output_root=tmp_path / "runs")
    for name, arm in pair["arms"].items():
        fixture = Fixture(run / name)
        hooks = [{"phase": "task", "event": "hook_started", "timestamp": "2026-09-18T12:00:00+00:00"}]
        for index, (tool, arguments) in enumerate(GOLDEN[case]):
            executed = fixture.call(transport_name(tool), arguments)
            base = {"phase": "task", "timestamp": f"2026-09-18T12:00:{index+1:02}+00:00",
                    "tool_name": "mcp__benchmark_fixture__" + transport_name(tool), "tool_input": arguments,
                    "call_id": f"call-{index}", "session_id": name, "transcript_path": str(run / name / "unit-only.raw.jsonl"), "turn_id": "unit-turn"}
            hooks += [{**base, "event": "tool_proposed"}, {**base, "event": "tool_completed", "tool_response": {
                "structuredContent": {"result": executed["result"], "fixture_call_id": executed["fixture_call_id"]}, "isError": False}}]
        Path(arm["hook_events"]).write_text("".join(json.dumps(hook) + "\n" for hook in hooks))
        session = run / name / "unit-session.jsonl"
        session.write_text(json.dumps({"type": "thread.started", "thread_id": name}) + "\n" + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": RESPONSES[case]}}) + "\n" + json.dumps({"type": "turn.completed"}) + "\n")
        arm.update(session_path=str(session), status="completed")
    write_json(run / "pair.json", pair)
    result = report(run)
    assert all(value["status"] == "passed" for value in result["results"].values()), result
    assert all(value["tokens"]["complete"] is False for value in result["results"].values())
    first = result["grade_archive"]
    assert Path(first).is_dir()
    assert report(run)["grade_archive"] != first
    assert Path(first).is_dir()
    if GOLDEN[case]:
        # A missing server→host execution link makes the result unknown, not passed.
        hooks_path = Path(pair["arms"]["baseline"]["hook_events"])
        rows = [json.loads(line) for line in hooks_path.read_text().splitlines()]
        rows[-1]["tool_response"] = {"content": []}
        hooks_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        assert report(run)["results"]["baseline"]["status"] == "unknown"
