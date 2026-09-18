from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import uuid
from importlib.resources import files
from pathlib import Path

from mcp import Client, StdioServerParameters

from .scenarios import expected_evidence
from .storage import digest, read_json, seed_database, timestamp, write_json

ASSETS = Path(str(files("rippletide_uat") / "assets"))


def scenarios() -> dict:
    return read_json(ASSETS / "scenarios.json")


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def server_command(kind: str, run: Path) -> dict:
    return {"command": sys.executable, "args": ["-m", "rippletide_uat", "serve", kind, "--run", str(run)]}


async def probe_server(kind: str, run: Path) -> dict:
    command = server_command(kind, run)
    args = StdioServerParameters(**command, env={"RIPPLETIDE_UAT_PHASE": "preflight"})
    expected = {"docs": ("search_documents", "get_document", "DOC-SESSION-2", "document_id"), "tracker": ("search_issues", "get_issue", "SESSION-17", "issue_id")}[kind]
    try:
        async with asyncio.timeout(20):
            async with Client(args) as client:
                available = await client.list_tools()
                tools = {item.name: item for item in available.tools}
                if not {expected[0], expected[1]}.issubset(tools):
                    raise ValueError("Required tools are missing from tools/list")
                result = await client.call_tool(expected[0], {"query": "session expiration deadline", "project": "session-alpha"})
                if result.is_error:
                    raise ValueError("Search protocol probe failed")
                fetched = await client.call_tool(expected[1], {expected[3]: expected[2]})
                if fetched.is_error or expected[2] not in fetched.model_dump_json():
                    raise ValueError("Fetch protocol probe returned no expected record")
                return {"status": "ready", "checked_at": timestamp(), "evidence": "MCP tools/list, tools/call search and fetch", "input_schema": tools[expected[0]].input_schema}
    except Exception as exc:
        return {"status": "unavailable", "checked_at": timestamp(), "evidence": f"{type(exc).__name__}: {exc}"}


def make_capabilities() -> list[dict]:
    shell_schema = {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
    search_schema = {"type": "object", "properties": {"query": {"type": "string"}, "project": {"type": "string"}, "limit": {"type": "integer", "default": 5}, "decision_id": {"type": ["string", "null"]}}, "required": ["query", "project"]}
    rg_ready = shutil.which("rg") is not None
    entries = [
        ("native.filename_search", "native", "repository_search", "Find repository files by filename or path using rg --files.", {"tool": "exec_command", "command_hint": "rg --files"}, shell_schema, rg_ready),
        ("native.lexical_search", "native", "repository_search", "Find exact text, symbols, or patterns in repository files using rg -n.", {"tool": "exec_command", "command_hint": "rg -n"}, shell_schema, rg_ready),
        ("mcp.semantic_search", "mcp", "repository_search", "Retrieve repository code by conceptual meaning through the existing Chroma MCP integration.", {"server": "uat_semantic", "tool": "chroma_query_documents"}, {"type": "object"}, False),
        ("mcp.docs_search", "mcp", "knowledge_lookup", "Find published project specifications, versioned documentation, and contributor guides.", {"server": "uat_docs", "tool": "search_documents"}, search_schema, False),
        ("mcp.tracker_search", "mcp", "knowledge_lookup", "Find reported bugs, reproductions, approved requirement changes, and historical issue proposals.", {"server": "uat_tracker", "tool": "search_issues"}, search_schema, False),
        ("agent.reviewer", "agent", "specialist_assignment", "Review bounded code changes for implementation correctness and concrete regressions.", {"agent_type": "rippletide_reviewer"}, {"type": "object", "properties": {"message": {"type": "string"}, "agent_type": {"const": "rippletide_reviewer", "type": "string"}}, "required": ["agent_type", "message"]}, False),
        ("agent.test_specialist", "agent", "specialist_assignment", "Assess test coverage and missing regression cases, execute checks, and specify expected outcomes.", {"agent_type": "rippletide_test_specialist"}, {"type": "object", "properties": {"message": {"type": "string"}, "agent_type": {"const": "rippletide_test_specialist", "type": "string"}}, "required": ["agent_type", "message"]}, False),
    ]
    capabilities = []
    for route, kind, operation, description, invocation, schema, ready in entries:
        capabilities.append({"id": route, "kind": kind, "operations": [operation], "description": description, "available": ready, "invocation": invocation, "input_schema": schema, "availability": {"status": "ready" if ready else "unavailable", "state": "configured-but-unverified" if kind == "agent" else "not-checked", "checked_at": timestamp(), "evidence": "rg is installed" if ready else "Requires real integration preflight"}})
    return capabilities


def render_codex_config(run: Path, workspace: Path, manifest: dict, servers: dict | None = None) -> None:
    servers = servers or manifest["servers"]
    lines = ["# Generated only for this disposable UAT project.", "[agents]", "max_threads = 2", ""]
    for role, description in (("rippletide_reviewer", "Review bounded changes for correctness regressions."), ("rippletide_test_specialist", "Assess missing regression tests and verification coverage.")):
        role_file = workspace / ".codex" / "agents" / f"{role}.toml"
        if role_file.exists():
            lines.extend([f"[agents.{role}]", f"description = {json.dumps(description)}", f"config_file = {json.dumps(str(role_file))}", ""])
    # Every fixture uses its explicit MCP server and skill configuration. Disable
    # any installed personal instance to prevent duplicate routing in C/D and
    # leakage into A/B. This only writes the disposable project configuration.
    lines.extend(['[plugins."rippletide@personal"]', 'enabled = false', ""])
    for name, server in servers.items():
        lines.extend([f"[mcp_servers.{name}]", f"command = {json.dumps(server['command'])}", f"args = {json.dumps(server.get('args', []))}", "enabled = true", "startup_timeout_sec = 60", ""])
        if server.get("env"):
            lines.append(f"[mcp_servers.{name}.env]")
            lines.extend(f"{key} = {json.dumps(value)}" for key, value in server["env"].items())
            lines.append("")
    skill = workspace / ".agents" / "skills" / "route-capabilities" / "SKILL.md"
    if skill.exists():
        lines.extend(["[[skills.config]]", f"path = {json.dumps(str(skill))}", f"enabled = {'true' if manifest['variant'] in {'C', 'D'} else 'false'}", ""])
    (workspace / ".codex" / "config.toml").write_text("\n".join(lines))


def write_project_config(run: Path, workspace: Path, manifest: dict, capabilities: list[dict], prefer: dict | None = None) -> None:
    write_json(workspace / ".rippletide" / "config.json", {"version": 1, "registry_version": "v1", "run_id": manifest["run_id"], "variant": manifest["variant"], "log_path": str(run / "router-events.jsonl"), "preferences": {"prefer": prefer or {}, "exclude": [], "exact_symbol_first": True}, "capabilities": capabilities})
    render_codex_config(run, workspace, manifest)


def source_snapshot(workspace: Path) -> dict:
    return {str(path.relative_to(workspace)): digest(path.read_text()) for path in sorted(workspace.rglob("*")) if path.is_file() and not any(part in {".codex", ".agents", ".rippletide", ".git", "__pycache__"} for part in path.relative_to(workspace).parts) and path.name != "AGENTS.md"}


def prepare(scenario_id: str, variant: str, output_root: Path, plugin_root: Path, *, run_id: str | None = None, failure: str | None = None, comparison_scenario: str = "U02") -> Path:
    if scenario_id not in scenarios() or variant not in "ABCD" or len(variant) != 1:
        raise ValueError("Choose U01-U09 and variant A, B, C, or D")
    if failure and scenario_id != "U07":
        raise ValueError("--failure applies only to U07")
    if scenario_id == "U07" and failure not in {"docs", "tracker", "reviewer", "test_specialist", "model"}:
        raise ValueError("U07 requires --failure docs|tracker|reviewer|test_specialist|model")
    if failure == "model" and variant != "D":
        raise ValueError("The Qwen backend failure scenario requires variant D")
    if comparison_scenario not in {"U02", "U05"}:
        raise ValueError("U09 compares U02 or U05")
    scenario = dict(scenarios()[comparison_scenario if scenario_id == "U09" else scenario_id])
    scenario["evidence"] = expected_evidence({"scenario": scenario_id, "scenario_definition": scenario})
    run_id = run_id or f"{scenario_id}-{variant}-{uuid.uuid4().hex[:12]}"
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run ID must be a single directory name")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run = output_root / run_id
    run.mkdir()  # atomic refusal to overwrite any existing run
    workspace = run / "workspace"
    template = ASSETS / "projects" / "session_service"
    if scenario["fixture"] == "taskboard":
        workspace.mkdir()
    else:
        shutil.copytree(template, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if scenario["fixture"] == "session_review":
        original = (workspace / "session_app" / "session_store.py").read_text()
        # This candidate fixes the deadline but accidentally drops revocation.
        candidate = original.replace('session is None or session.get("revoked", False)', 'session is None').replace('now > session["expires_at"]', 'now >= session["expires_at"]')
        (workspace / "session_app" / "session_store.py").write_text(candidate)
        (workspace / "BASELINE_SESSION_STORE.txt").write_text(original)
    shutil.copytree(ASSETS / "agents", workspace / ".codex" / "agents")
    routing_skill = plugin_root / "skills" / "route-capabilities"
    if variant in {"C", "D"} and routing_skill.is_dir():
        shutil.copytree(routing_skill, workspace / ".agents" / "skills" / "route-capabilities")
    data = read_json(ASSETS / "records.json")
    for kind in ("docs", "tracker"):
        seed_database(run / f"{kind}.sqlite3", data[kind])
    for filename in ("router-events.jsonl", "tool-events.jsonl", "interventions.jsonl"):
        (run / filename).touch()
    servers = {f"uat_{kind}": server_command(kind, run) for kind in ("docs", "tracker")}
    if variant in {"C", "D"}:
        servers["rippletide"] = {"command": shutil.which("uv") or "uv", "args": ["run", "--locked", "--project", str(plugin_root.resolve()), "rippletide", "serve"]}
        if failure == "model":
            servers["rippletide"]["env"] = {"RIPPLETIDE_DATA_DIR": str(run / "deliberately-unavailable-model")}
    manifest = {"schema_version": 1, "run_id": run_id, "scenario": scenario_id, "comparison_scenario": comparison_scenario if scenario_id == "U09" else None, "variant": variant, "created_at": timestamp(), "workspace": str(workspace), "plugin_root": str(plugin_root.resolve()), "python": sys.executable, "fixture_version": "0.1.0", "project": scenario["project"], "scenario_definition": scenario, "servers": servers, "failure": failure, "intervention_ledger_complete": False, "task_outcome": "unknown", "session": None, "usage": None, "manual_checks": {}}
    write_json(run / "run.json", manifest)
    guidance = f"# Test project\n\nProject: {scenario['project']}. Work within this project and its connected MCP services. Do not inspect parent directories, fixture databases, grader source, evaluation answers, or the plugin implementation. Use the exposed tools and project files for evidence. Connected uat_docs and uat_tracker contain synthetic project documentation and issues. Custom reviewer and test-specialist agents are available for bounded specialist work when requested; use the applicable role, wait for its result, and incorporate it. Do not delegate further from a specialist.\n"
    if variant in {"C", "D"}:
        guidance += "\nUse the Rippletide route-capabilities skill for eligible repository_search, knowledge_lookup, and specialist_assignment decisions. Supply the current workspace as project_root. Follow the selected mapping and generate the real tool arguments yourself. Carry decision_id into fixture tool arguments and specialist assignment text. If routing defers or fails, continue normally without repeatedly routing the same decision. Never route report/status calls.\n"
    elif variant == "B":
        guidance += "\nChoose tools consistently: known filenames suggest path search; known symbols suggest exact-text search; conceptual questions can use available semantic retrieval. Consult published documentation for specifications and the tracker for issues/approved changes. Choose a reviewer for code correctness and a test specialist for missing regression cases. Resolve uncertainty yourself.\n"
    (workspace / "AGENTS.md").write_text(guidance)
    capabilities = make_capabilities()
    for kind, route_id in (("docs", "mcp.docs_search"), ("tracker", "mcp.tracker_search")):
        readiness = asyncio.run(probe_server(kind, run))
        capability = next(entry for entry in capabilities if entry["id"] == route_id)
        capability["available"] = readiness["status"] == "ready"
        capability["availability"] = readiness
        if "input_schema" in readiness:
            capability["input_schema"] = readiness.pop("input_schema")
    if failure in {"docs", "tracker"}:
        manifest["servers"].pop(f"uat_{failure}")
        for capability in capabilities:
            if capability["id"] == f"mcp.{failure}_search":
                capability.update(available=False, availability={"status": "unavailable", "state": "deliberately-disabled", "evidence": "U07 dependency failure"})
    if failure in {"reviewer", "test_specialist"}:
        (workspace / ".codex" / "agents" / f"rippletide_{failure}.toml").unlink()
        for capability in capabilities:
            if capability["id"] == f"agent.{failure}":
                capability["availability"]["state"] = "deliberately-disabled"
    write_project_config(run, workspace, manifest, capabilities, {"repository_search": "native.filename_search"} if scenario_id == "U06" else None)
    if scenario_id == "U06":
        sibling = run / "workspace-secondary"
        shutil.copytree(template, sibling, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ASSETS / "agents", sibling / ".codex" / "agents")
        if variant in {"C", "D"} and routing_skill.is_dir():
            shutil.copytree(routing_skill, sibling / ".agents" / "skills" / "route-capabilities")
        (sibling / "AGENTS.md").write_text(guidance.replace("session-alpha", "session-beta"))
        write_project_config(run, sibling, manifest, capabilities, {"repository_search": "native.lexical_search"})
        manifest["secondary_workspace"] = str(sibling)
        manifest["secondary_initial_preferences"] = read_json(sibling / ".rippletide" / "config.json")["preferences"]
    manifest["source_snapshot"] = source_snapshot(workspace)
    manifest["source_snapshot_hash"] = digest(manifest["source_snapshot"])
    manifest["initial_preferences"] = read_json(workspace / ".rippletide" / "config.json")["preferences"]
    write_json(run / "run.json", manifest)
    (run / "prompt.txt").write_text(scenario["prompt"] + "\n")
    if scenario.get("followup"):
        (run / "followup.txt").write_text(scenario["followup"] + "\n")
    preflight_roles = [path.stem for path in sorted((workspace / ".codex" / "agents").glob("*.toml"))]
    (run / "agent-preflight-prompt.txt").write_text(f"Setup verification only: invoke {', '.join(preflight_roles)} as real named custom agents. Give each the bounded read-only task of identifying its role and listing one existing project file (or reporting an empty application workspace). Wait for all requested agents and return their actual results. Do not call Rippletide for these setup choices and do not change project files.\n")
    return run


def prepare_semantic(run: Path, integration_root: Path) -> dict:
    manifest = read_json(run / "run.json")
    command = [shutil.which("uv") or "uv", "run", "--locked", "--project", str(integration_root.resolve()), "rippletide-semantic", "index", "--workspace", manifest["workspace"], "--data-dir", str(run / "chroma"), "--collection", "rippletide_workspace"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode:
        return {"ready": False, "error": completed.stderr or completed.stdout, "exit_code": completed.returncode}
    result = json.loads(completed.stdout)
    if not result.get("ready") or not result.get("server_config"):
        return {"ready": False, "error": "Semantic helper did not report readiness", "result": result}
    manifest["servers"]["uat_semantic"] = result["server_config"]
    config_path = Path(manifest["workspace"]) / ".rippletide" / "config.json"
    config = read_json(config_path)
    capability = next(item for item in config["capabilities"] if item["id"] == "mcp.semantic_search")
    capability.update(available=True, input_schema=result["input_schema"], availability={"status": "ready", "checked_at": timestamp(), "evidence": "Upstream Chroma MCP index/protocol check", "collection_name": result["collection_name"]})
    capability["invocation"]["collection_name"] = result["collection_name"]
    write_json(config_path, config)
    write_json(run / "run.json", manifest)
    render_codex_config(run, Path(manifest["workspace"]), manifest)
    return result
