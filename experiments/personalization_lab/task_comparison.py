"""Real Codex task pilot using isolated development plugin components.

This verifies skills/MCP/hooks/tool execution, not marketplace installation.
Each arm starts from a fresh copy of the existing U05 acceptance fixture.
"""
from __future__ import annotations

import json
import copy
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

from rippletide.personalization import atomic_json, read_json, digest, init_profile, activate
from rippletide.identity import model_identity
from rippletide_uat.prepare import prepare, source_snapshot
from rippletide_uat.paired_host import (pinned_codex, verify_codex, clean_environment,
    link_auth, unlink_auth, write_config, capture_session, project_root)
from rippletide_uat.paired import TASK_BOUNDARY, completed_specialists, model_readiness
from rippletide_uat.graders import grade_sessions
from rippletide_uat.storage import read_events
from .dataset import read_rows, training_history, preferences

ARMS = ("baseline", "current", "memory", "residual", "lora")


def task_call_evidence(events: list[dict], session: dict) -> list[dict]:
    # Fixture processes may not inherit the phase environment variable. Use
    # the measured task interval as well, so setup calls cannot inflate success.
    return [e for e in events if e.get("event") == "tool_call"
            and session["started_at"] <= e.get("timestamp", "") <= session["finished_at"]
            and e.get("status") == "success"]


def requirements_verified(acceptance, specialists, tool_calls):
    records = {record for call in tool_calls for record in call.get("returned_record_ids", [])}
    return acceptance["status"] == "passed" and bool(specialists) and {"DOC-SESSION-2", "SESSION-17"} <= records


def task_profile(path: Path, arm: str, dataset: Path, component_run: Path, user: str) -> None:
    init_profile(path, user_id=user, preferences=preferences(user), mode="off" if arm == "current" else "memory")
    if arm == "current":
        return
    train = [r for r in read_rows(dataset, "train") if r["user_id"] == user and r["kind"] != "rule"]
    random.Random(31).shuffle(train)
    atomic_json(path / "feedback.json", training_history(train[:12], user))
    if arm in {"residual", "lora"}:
        source = component_run / (f"policies/{user}.json" if arm == "residual" else f"adapters/{user}")
        gate = read_json(component_run / (f"policies/{user}-validation.json" if arm == "residual" else f"adapters/{user}/validation.json"))
        # Never quietly run a rejected candidate as the production policy.
        if not gate["passed"]:
            raise ValueError(f"{arm} failed its validation gate; use the memory arm as the deployed behavior")
        target = path / "versions" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
        identity = model_identity("qwen3-0.6b-torch")
        activate(path, mode=arm, artifact=target, base_identity=identity, backend="torch", validation=gate)


def run_task(output: Path, dataset: Path, component_run: Path, data_dir: Path, *, arm: str,
             model: str, effort: str = "high", user: str = "developer_a", timeout: int = 900) -> dict:
    if arm not in ARMS:
        raise ValueError("Unknown task comparison arm")
    executable = pinned_codex()
    version = verify_codex(executable)
    root = project_root()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run = output / arm
    if run.exists():
        raise FileExistsError("Task runs are immutable; choose a fresh output directory")
    run = prepare("U05", "A" if arm == "baseline" else "D", output,
                  root / "plugins/rippletide", run_id=arm)
    manifest = read_json(run / "run.json")
    workspace, home = Path(manifest["workspace"]), run / "codex-home"
    before = source_snapshot(workspace)
    profile_path = run / "learning-profile"
    if arm != "baseline":
        task_profile(profile_path, arm, dataset, component_run, user)
    # Keep all task configuration in a private Codex home. No installed user
    # plugin/configuration is changed, and no fixture copy can shadow it.
    config_path = workspace / ".codex/config.toml"
    config_path.rename(run / "generated-project-config.toml")
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    env = clean_environment()
    env.update(CODEX_HOME=str(home), PYTHONUTF8="1", RIPPLETIDE_RUN_DIR=str(run),
        RIPPLETIDE_PROJECT_ROOT=str(workspace), RIPPLETIDE_RUN_ID=arm,
        RIPPLETIDE_PHASE="task", RIPPLETIDE_UAT_PHASE="task",
        RIPPLETIDE_HOOK_MODE="observe" if arm == "baseline" else "enforce",
        RIPPLETIDE_MODEL="qwen3-0.6b-torch", RIPPLETIDE_DATA_DIR=str(data_dir.resolve()),
        RIPPLETIDE_PROFILE=str(profile_path), RIPPLETIDE_EXPERIMENT_TIMEOUT="120",
        RIPPLETIDE_CPU_THREADS="4")
    servers = {name: {**server, "startup_timeout_sec": 180, "tool_timeout_sec": 150}
               for name, server in manifest["servers"].items()}
    if arm != "baseline":
        servers["rippletide"] = {"command": sys.executable,
            "args": [str(root / "scripts/personalization_task_mcp.py")],
            "env": {key: value for key, value in env.items() if key.startswith("RIPPLETIDE_")},
            "startup_timeout_sec": 180, "tool_timeout_sec": 150}
    agents = {}
    for file in sorted((workspace / ".codex/agents").glob("*.toml")):
        agents[file.stem] = {"description": file.stem.replace("_", " "), "config_file": str(file)}
    guard = root / "plugins/rippletide/scripts/guard.py"
    command = f'"{sys.executable}" "{guard}"'
    handler = {"type": "command", "command": command, "timeout": 5}
    if os.name == "nt":
        python_literal = str(sys.executable).replace("'", "''")
        guard_literal = str(guard).replace("'", "''")
        handler["command_windows"] = f'powershell.exe -NoProfile -NonInteractive -Command "& \'{python_literal}\' \'{guard_literal}\'"'
    config = {"model": model, "model_reasoning_effort": effort, "approval_policy": "never",
        "sandbox_mode": "workspace-write", "web_search": "disabled", "features": {"hooks": True},
        "projects": {str(workspace): {"trust_level": "trusted"}},
        "mcp_servers": servers, "agents": {"max_threads": 3, **agents},
        "hooks": {"SessionStart": [{"hooks": [handler]}],
                  "PreToolUse": [{"matcher": "*", "hooks": [handler]}],
                  "PostToolUse": [{"matcher": "*", "hooks": [handler]}]}}
    if os.name == "nt":
        config["windows"] = {"sandbox": "unelevated"}
    write_config(home, config)
    prompt = (TASK_BOUNDARY + "\n" + manifest["scenario_definition"]["prompt"] +
        "\nAlso inspect the reported expired-session issue in the connected tracker. "
        "Use a named specialist for the requested review. My routing preferences:\n" +
        "\n".join(preferences(user)) + f"\nAvailable test interpreter: {sys.executable}\n")
    (run / "task-prompt.txt").write_text(prompt, encoding="utf-8")
    metadata = {"level": "end-to-end isolated development components; not marketplace installation",
        "arm": arm, "model": model, "effort": effort, "codex_version": version,
        "user": user, "initial_snapshot": before, "initial_snapshot_digest": digest(before),
        "routing_model": "qwen3-0.6b-torch" if arm != "baseline" else None,
        "route_deadline_seconds": 120 if arm != "baseline" else None,
        "production_deadline_seconds": 2, "same_preferences_in_parent_prompt": True}
    atomic_json(run / "task-manifest.json", metadata)
    auth = link_auth(home)
    try:
        preflight_dir = run / "preflight"
        preflight_dir.mkdir()
        preflight_env = {**env, "RIPPLETIDE_PHASE": "preflight", "RIPPLETIDE_UAT_PHASE": "preflight"}
        preflight_config = copy.deepcopy(config)
        for server in preflight_config["mcp_servers"].values():
            server.setdefault("env", {}).update(RIPPLETIDE_UAT_PHASE="preflight", RIPPLETIDE_PHASE="preflight")
        write_config(home, preflight_config)
        probe = ("Setup check only. Run exec_command with the command Write-Output rippletide-ready. "
            "Verify the configured MCP tools by calling uat_docs.search_documents with query readiness and project session-alpha, "
            "and uat_tracker.search_issues with the same arguments. An empty resources list is not evidence that tools are unavailable; "
            "discover and invoke the named tools. "
            "Then invoke both named roles rippletide_reviewer and rippletide_test_specialist for the bounded task "
            "of stating their role; they must not edit files, call tools, or delegate. Wait for both. "
            "Do not perform the actual project task yet. Do not route these setup checks.")
        if arm != "baseline":
            probe += f" Call rippletide.status with project_root {workspace} and report whether its configured model worker is ready."
        preflight = capture_session(executable, home=home, workspace=workspace, run=preflight_dir,
            environment=preflight_env, prompt=probe, timeout=180)
        host_events = read_events(Path(preflight["stdout"]))
        observed_mcp = {e.get("item", {}).get("server") for e in host_events
                       if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "mcp_tool_call"
                       and e["item"].get("status") == "completed" and not e["item"].get("error")}
        proof = {"session": preflight, "hooks": read_events(run / "hook-events.jsonl"), "mcp_servers": sorted(observed_mcp),
                 "specialists": sorted(completed_specialists(preflight.get("child_rollouts", [])))}
        if arm != "baseline":
            proof["model"] = model_readiness(run / "hook-events.jsonl", "qwen3-0.6b-torch", workspace)
        atomic_json(run / "preflight-results.json", proof)
        if not proof["hooks"] or not set(agents) <= set(proof["specialists"]) or not {"uat_docs", "uat_tracker"} <= observed_mcp:
            raise RuntimeError("Task blocked: hook, MCP or specialist preflight failed; evidence retained")
        if arm != "baseline" and not proof["model"]["ready"]:
            raise RuntimeError("Task blocked: configured model worker was not ready; preflight evidence retained")
        if arm != "baseline":
            registry_path = workspace / ".rippletide/config.json"
            registry = read_json(registry_path)
            for cap in registry["capabilities"]:
                if cap["kind"] == "agent":
                    cap["available"] = cap["invocation"]["agent_type"] in proof["specialists"]
                    cap["availability"] = {"status": "ready", "evidence": "completed named specialist preflight"}
            atomic_json(registry_path, registry)
        write_config(home, config)
        result = capture_session(executable, home=home, workspace=workspace, run=run,
            environment=env, prompt=prompt, timeout=timeout)
    finally:
        unlink_auth(auth)
    acceptance = grade_sessions(workspace)
    events = read_events(run / "tool-events.jsonl")
    routes = read_events(run / "router-events.jsonl")
    hooks = read_events(run / "hook-events.jsonl")
    tool_calls = task_call_evidence(events, result)
    specialists = sorted(completed_specialists(result.get("child_rollouts", [])))
    # Evidence remains distinct: correct code does not prove routing or review.
    final = {"manifest": metadata, "preflight": proof, "session": result, "acceptance": acceptance,
        "completed_specialists": specialists, "actual_fixture_calls": tool_calls,
        "routing_decisions": routes, "hook_event_count": len(hooks),
        "final_snapshot": source_snapshot(workspace),
        "task_requirements_verified": requirements_verified(acceptance, specialists, tool_calls)}
    atomic_json(run / "task-results.json", final)
    return final
