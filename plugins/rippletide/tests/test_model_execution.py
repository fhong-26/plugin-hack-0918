"""Public black-box developer integration, not a Codex user-acceptance run.

The fixture is prepared with its CLI. Only public MCP tools, returned invocation
metadata, and real subprocess commands are used. No router or test-kit Python
implementation is imported. Native rg execution here is a Python subprocess,
not evidence that Codex itself executed a native tool. Agents remain untouched.
"""

import asyncio
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.model


def _payload(result):
    assert not result.is_error, result.model_dump_json()
    assert isinstance(result.structured_content, dict), result.model_dump_json()
    return result.structured_content


def _client_parameters(command):
    return StdioServerParameters(
        command=command["command"], args=command.get("args", []),
        env={**os.environ, **command.get("env", {})},
    )


def test_model_selected_tools_execute_through_public_interfaces(tmp_path, capsys):
    repository = Path(__file__).resolve().parents[3]
    plugin = Path(__file__).resolve().parents[1]
    test_kit = repository / "user_tests"
    assert (test_kit / "uv.lock").is_file(), "This repository integration test requires the user_tests package"
    uv = shutil.which("uv")
    assert uv and shutil.which("rg"), "uv and rg are required for the real public-interface integration"
    # Setting an output root retains explicit evidence outside pytest's temp area.
    output = Path(os.environ.get("RIPPLETIDE_INTEGRATION_OUTPUT_ROOT", str(tmp_path / "runs")))
    prepared = subprocess.run(
        [uv, "run", "--locked", "--project", str(test_kit), "rippletide-uat", "prepare",
         "--scenario", "U02", "--variant", "D", "--output-root", str(output), "--plugin-root", str(plugin)],
        capture_output=True, text=True, timeout=90,
    )
    assert prepared.returncode == 0, prepared.stderr
    paths = json.loads(prepared.stdout)
    run, workspace = Path(paths["run"]), Path(paths["workspace"])
    manifest = json.loads((run / "run.json").read_text())
    evidence = {
        "evidence_kind": "developer_public_interface_integration",
        "not_user_acceptance": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run": str(run), "workspace": str(workspace),
        "agent_execution": "not_attempted", "executions": [],
    }

    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "rippletide", "serve"], env=dict(os.environ))
        server_started = time.perf_counter()
        async with Client(params) as router:
            initialized_ms = (time.perf_counter() - server_started) * 1000
            listing = await router.list_tools()
            metadata = {tool.name: tool.annotations for tool in listing.tools}
            assert metadata["route"].read_only_hint is False
            assert all(metadata[name].read_only_hint is True for name in ("status", "report"))
            assert all(value.destructive_hint is False and value.open_world_hint is False for value in metadata.values())
            evidence["tool_annotations"] = {name: annotations.model_dump(by_alias=True, exclude_none=True) for name, annotations in metadata.items()}
            initial = _payload(await router.call_tool("status", {"project_root": str(workspace)}))
            assert initial["model_installed"], initial
            evidence["initial_worker_state"] = initial["worker"]["state"]
            evidence["server_initialized_ms"] = initialized_ms
            native_request = {
                "project_root": str(workspace), "operation": "repository_search",
                "goal": "Find the exact text validate_identity inside the repository source files.",
                "facts": {}, "recent_observations": [],
            }
            # MCP initialization does not wait for MLX. A first unresolved request
            # may defer while the background worker is loading; no result is invented.
            cold_started = time.perf_counter()
            cold = _payload(await router.call_tool("route", native_request))
            evidence["cold_first_route"] = cold
            evidence["cold_first_route_wall_ms"] = (time.perf_counter() - cold_started) * 1000
            assert cold["status"] == "selected" or cold["reason_code"] == "MODEL_NOT_READY", cold
            assert evidence["cold_first_route_wall_ms"] < 2100
            deadline = time.perf_counter() + 30
            while not initial["worker"]["ready"]:
                assert time.perf_counter() < deadline, initial
                await asyncio.sleep(0.1)
                initial = _payload(await router.call_tool("status", {"project_root": str(workspace)}))
            worker_pid = initial["worker"]["pid"]
            evidence["ready_after_ms"] = (time.perf_counter() - server_started) * 1000
            evidence["model_identity"] = initial["model_identity"]
            assert initial["model_identity"]["engine_revision"] == "2af86848be75847ccb3553b0941cc51d6ef7e4e9"
            assert initial["model_identity"]["weights_revision"] == "8b403126fc14f14cfc99bb4cfa72ecbc129ea677"
            assert not any(cap["available"] for cap in initial["supported_capabilities"] if cap["kind"] == "agent")

            native = _payload(await router.call_tool("route", native_request))
            assert native["source"] == "model" and native["status"] == "selected", native
            assert native["route_id"] == "native.lexical_search", native
            assert native["invocation"] == {"tool": "exec_command", "command_hint": "rg -n"}
            command = ["rg", "-n", "validate_identity", "session_app"]
            executed = await asyncio.to_thread(subprocess.run, command, cwd=workspace, capture_output=True, text=True, timeout=5)
            assert executed.returncode == 0, executed.stderr
            assert "session_app/identity.py:1:def validate_identity" in executed.stdout
            evidence["executions"].append({
                "category": "native", "executor": "python_subprocess_rg_not_codex",
                "decision": native, "command": command, "exit_code": executed.returncode,
                "stdout_sha256": hashlib.sha256(executed.stdout.encode()).hexdigest(),
                "matched_lines": executed.stdout.splitlines(),
            })

            queries = [
                {
                    "goal": "Find the published project specification for the current session expiration policy.",
                    "route": "mcp.docs_search", "server": "uat_docs", "tool": "search_documents",
                    "query": "session expiration requirements", "record": "DOC-SESSION-2",
                    "fetch": "get_document", "id_parameter": "document_id",
                },
                {
                    "goal": "Find the reported expired-session bug ticket and its reproduction steps.",
                    "route": "mcp.tracker_search", "server": "uat_tracker", "tool": "search_issues",
                    "query": "expired session deadline", "record": "SESSION-17",
                    "fetch": "get_issue", "id_parameter": "issue_id",
                },
            ]
            for query in queries:
                decision = _payload(await router.call_tool("route", {
                    "project_root": str(workspace), "operation": "knowledge_lookup",
                    "goal": query["goal"], "facts": {}, "recent_observations": [],
                }))
                assert decision["source"] == "model" and decision["status"] == "selected", decision
                assert decision["route_id"] == query["route"], decision
                invocation = decision["invocation"]
                assert invocation == {"server": query["server"], "tool": query["tool"]}
                async with Client(_client_parameters(manifest["servers"][invocation["server"]])) as target:
                    search = _payload(await target.call_tool(invocation["tool"], {
                        "query": query["query"], "project": "session-alpha", "decision_id": decision["decision_id"],
                    }))
                    ids = [record["id"] for record in search["records"]]
                    assert query["record"] in ids, search
                    fetched = _payload(await target.call_tool(query["fetch"], {
                        query["id_parameter"]: query["record"], "decision_id": decision["decision_id"],
                    }))
                    assert fetched["id"] == query["record"] and fetched["body"]
                evidence["executions"].append({
                    "category": "mcp", "executor": "official_mcp_client",
                    "decision": decision, "invoked": invocation, "returned_record_ids": ids,
                    "fetched_record_id": fetched["id"], "source_uri": fetched["source_uri"],
                })

            status_ms, route_ms, wall_ms = [], [], []
            for _ in range(5):
                started = time.perf_counter()
                status = _payload(await router.call_tool("status", {"project_root": str(workspace)}))
                status_ms.append((time.perf_counter() - started) * 1000)
                assert status["worker"]["pid"] == worker_pid and status["worker"]["ready"]
                started = time.perf_counter()
                repeated = _payload(await router.call_tool("route", native_request))
                wall_ms.append((time.perf_counter() - started) * 1000)
                assert repeated["source"] == "model" and repeated["route_id"] == native["route_id"], repeated
                assert repeated["worker_pid"] == worker_pid
                assert repeated["elapsed_ms"] <= 2000 and wall_ms[-1] < 2100
                route_ms.append(repeated["elapsed_ms"])
            evidence["warm_routing_ms"] = route_ms
            evidence["warm_mcp_roundtrip_ms"] = wall_ms
            evidence["status_roundtrip_ms"] = status_ms
            evidence["warm_routing_p95_ms"] = sorted(route_ms)[math.ceil(0.95 * len(route_ms)) - 1]
            evidence["sample_meets_500ms_target"] = evidence["warm_routing_p95_ms"] <= 500
            evidence["worker_reused"] = True
            report = _payload(await router.call_tool("report", {"project_root": str(workspace)}))
            assert report["actual_execution"] == "unknown", "Router-only reports must not manufacture execution evidence"
            evidence["router_report"] = report

        tool_events = [json.loads(line) for line in (run / "tool-events.jsonl").read_text().splitlines()]
        for execution in evidence["executions"]:
            if execution["category"] == "mcp":
                matches = [event for event in tool_events if event.get("decision_id") == execution["decision"]["decision_id"]]
                assert any(event["tool"] == execution["invoked"]["tool"] and event["status"] == "success" for event in matches)
        # A developer tool check leaves the end-user task and intervention ledger unresolved.
        final_manifest = json.loads((run / "run.json").read_text())
        assert final_manifest["task_outcome"] == "unknown"
        assert final_manifest["intervention_ledger_complete"] is False

    try:
        asyncio.run(exercise())
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["failure"] = str(exc)
        raise
    finally:
        (run / "public-integration-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        with capsys.disabled():
            print(f"\nPublic integration evidence: {run / 'public-integration-evidence.json'}")


def test_public_server_disconnect_during_loading_is_quiet(tmp_path):
    async def exercise():
        stderr_path = tmp_path / "early-disconnect.stderr"
        with stderr_path.open("w") as diagnostics:
            params = StdioServerParameters(command=sys.executable, args=["-m", "rippletide", "serve"], env=dict(os.environ))
            async with stdio_client(params, errlog=diagnostics) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    status = _payload(await client.call_tool("status", {"project_root": str(tmp_path)}))
                    assert status["model_installed"], status
                    assert status["worker"]["state"] in {"loading", "ready"}, status
            # The client leaves immediately, without waiting for inference readiness.
            await asyncio.sleep(1)
        log = stderr_path.read_text()
        assert "BrokenPipeError" not in log, log
        assert "Traceback" not in log, log
    asyncio.run(exercise())
