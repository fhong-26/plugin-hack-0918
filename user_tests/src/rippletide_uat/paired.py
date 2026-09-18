"""Bring-your-own-project baseline/Rippletide experiments, never in the source checkout."""

from __future__ import annotations

import copy
import asyncio
from contextlib import AsyncExitStack
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .paired_host import (authenticated, capture_session, clean_environment, link_auth, pinned_codex,
                          project_root, run_process, unlink_auth, verify_codex, write_config)
from .profiles import MODEL_OPTIONS, data_root, load_profile, repo_root
from .storage import read_events, read_json, timestamp, write_json


ARMS = ("baseline", "rippletide")
TASK_BOUNDARY = """Work only in this disposable project and the explicitly connected read-only information tools.
Implement the requested task and verify it with available project checks. Do not update tickets,
send messages, push, open PRs, change external systems, access other checkouts, or inspect the
runner's private logs, configuration, evaluator, or independent graders. Do not commit.
Any specialist must perform bounded read-only work, inherit your model settings, and not delegate.
Wait for all specialists you launch. Report failures and missing prerequisites honestly.
"""


def expand(value, replacements: dict[str, str]):
    if isinstance(value, str):
        for key, replacement in replacements.items():
            value = value.replace("{" + key + "}", replacement)
        return value
    if isinstance(value, list):
        return [expand(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, replacements) for key, item in value.items()}
    return value


def native_capabilities() -> list[dict]:
    return [{"id": f"native.{name}_search", "kind": "native", "operations": ["repository_search"],
             "description": description, "available": shutil.which("rg") is not None,
             "invocation": {"tool": "exec_command", "command_hint": hint},
             "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}
            for name, description, hint in (
                ("filename", "Find repository files by filename or path.", "rg --files"),
                ("lexical", "Find exact text, symbols, errors or implementation keywords.", "rg -n"))]


def snapshot_profile(profile: dict, run: Path) -> dict:
    """Freeze approved specialists and standalone external graders before either arm starts."""
    profile = copy.deepcopy(profile)
    for name, agent in profile["tools"]["agents"].items():
        source = Path(agent["config_file"])
        destination = run / "configuration/agents" / f"{name}.toml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        agent["config_file"] = str(destination)
    frozen_checks = []
    checks = [(command, False) for command in profile["checks"]]
    checks.extend((command, True) for command in profile.get("independent_checks", []))
    for index, (command, independent) in enumerate(checks):
        argv, hashes, grader_files = list(command), {}, []
        for position, item in enumerate(argv[1:], 1):
            path = Path(item)
            if not path.is_absolute() or not path.is_file() or path.is_relative_to(Path(profile["repo"])):
                continue
            target = run / "evaluation" / f"{index}-{position}-{path.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            hashes[str(position)] = hashlib.sha256(target.read_bytes()).hexdigest()
            argv[position] = str(target)
            if path.suffix in {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".rb"} and command[position - 1] not in {"-c", "--config", "--config-file"}:
                grader_files.append(str(position))
        if independent and not grader_files:
            raise ValueError("Independent checks require an explicitly supplied external grader source file (for example python /path/grader.py {workspace}), not only external configuration")
        frozen_checks.append({"argv": argv, "independence": "external" if independent else "project_checks", "file_hashes": hashes,
                              "grader_approval": "explicit_independent_check" if independent else "project_check",
                              "grader_file_arguments": grader_files if independent else []})
    profile["frozen_checks"] = frozen_checks
    return profile


def prepare_pair(repo: Path, prompt: str, *, base: str = "main", router_model: str = "qwen25-rlcd",
                 mode: str = "parallel", output_root: Path | None = None) -> tuple[Path, dict]:
    if router_model not in MODEL_OPTIONS or mode not in {"parallel", "sequential"}:
        raise ValueError("Unsupported router model or execution mode")
    if not prompt.strip() or len(prompt.encode()) > 100_000:
        raise ValueError("Task must contain text and be at most 100,000 UTF-8 bytes")
    root = repo_root(repo)
    profile = load_profile(root)
    base_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--verify", f"{base}^{{commit}}"], text=True).strip()
    run_id = "pair-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:10]
    destination = (output_root or data_root() / "runs").expanduser().resolve()
    if destination == root or destination.is_relative_to(root):
        raise ValueError("Paired output must be outside the source repository")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = destination / run_id
    run.mkdir(mode=0o700)
    profile = snapshot_profile(profile, run)
    manifest = {"schema_version": 1, "run_id": run_id, "repo": str(root), "base": base,
                "base_sha": base_sha, "prompt": prompt, "mode": mode, "router_model": router_model,
                "created_at": timestamp(), "profile": profile, "arms": {}, "status": "preparing",
                "resource_contention": mode == "parallel", "benchmark_validated": False}
    (run / "task.txt").write_text(prompt + "\n")
    for name in ARMS:
        arm_run = run / name
        arm_run.mkdir(mode=0o700)
        workspace = arm_run / "workspace"
        branch = f"test/rippletide-{run_id}-{name}"
        arm = {"run_id": f"{run_id}-{name}", "workspace": str(workspace), "branch": branch,
               "status": "setup-blocked", "wall_seconds": None, "session_path": None,
               "parent_rollout": None, "child_rollouts": [], "exit_code": None,
               "acceptance": [], "router_events": str(arm_run / "router-events.jsonl"),
               "hook_events": str(arm_run / "hook-events.jsonl"), "interventions": [],
               "interventions_complete": False, "settings": {"model": profile["model"], "effort": profile["effort"],
                   "sandbox": "workspace-write", "approval_policy": "never"}}
        manifest["arms"][name] = arm
        write_json(run / "pair.json", manifest)
        try:
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-b", branch, str(workspace), base_sha],
                           capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError:
            arm["setup_error"] = "Git worktree creation failed; any already-created arm is retained"
            write_json(run / "pair.json", manifest)
            raise
        # No copied ignored databases, .env files, dependency directories, or
        # existing working-tree edits enter either arm.
        arm["base_sha"] = subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True).strip()
    write_json(run / "pair.json", manifest)
    return run, manifest


def _json_command(command: list[str], *, cwd: Path, environment: dict, timeout: float = 60):
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f"Preflight command failed ({result.returncode}); no task launched: {command[:3]}")
    return json.loads(result.stdout)


def _hook_config(guard: Path) -> dict:
    handler = {"type": "command", "command": f"python3 {shlex.quote(str(guard))}", "timeout": 5}
    return {"SessionStart": [{"hooks": [handler]}],
            "PreToolUse": [{"matcher": "*", "hooks": [handler]}],
            "PostToolUse": [{"matcher": "*", "hooks": [handler]}]}


async def probe_capabilities(servers: dict, capabilities: list[dict], environment: dict) -> dict:
    """Check actual tools/list schemas; never issue a provider write or task call."""
    from mcp import Client, StdioServerParameters
    from mcp.client.streamable_http import streamable_http_client
    import httpx2

    evidence = {}
    for name, server in servers.items():
        async with asyncio.timeout(30), AsyncExitStack() as stack:
            if "command" in server:
                server_environment = clean_environment(names=server.get("env_vars", []))
                if "CODEX_API_KEY" not in server.get("env_vars", []):
                    server_environment.pop("CODEX_API_KEY", None)
                transport = StdioServerParameters(command=server["command"], args=server.get("args", []),
                                                  cwd=server.get("cwd"), env=server_environment)
            else:
                token_name = server.get("bearer_token_env_var")
                if token_name and not environment.get(token_name):
                    raise ValueError(f"Required credential environment variable is unavailable: {token_name}")
                headers = {"Authorization": f"Bearer {environment[token_name]}"} if token_name else {}
                http = await stack.enter_async_context(httpx2.AsyncClient(headers=headers))
                transport = streamable_http_client(server["url"], http_client=http)
            client = await stack.enter_async_context(Client(transport))
            catalog = await client.list_tools()
            found = {item.name: item for item in catalog.tools}
            while catalog.next_cursor:
                catalog = await client.list_tools(cursor=catalog.next_cursor)
                found.update({item.name: item for item in catalog.tools})
            if set(server["enabled_tools"]) - set(found):
                raise ValueError(f"Configured tools are missing from {name} tools/list")
            for tool in server["enabled_tools"]:
                annotation = found[tool].annotations
                if annotation and (annotation.destructive_hint is True or annotation.read_only_hint is False):
                    raise ValueError(f"Provider marks allowlisted {name}.{tool} as destructive or not read-only")
            evidence[name] = {"status": "ready", "source": "MCP tools/list", "checked_at": timestamp(), "tools": server["enabled_tools"]}
            for capability in capabilities:
                invocation = capability["invocation"]
                if capability["kind"] == "mcp" and invocation.get("server") == name:
                    capability.update(input_schema=found[invocation["tool"]].input_schema, available=True,
                                      availability={"status": "ready", "evidence": "MCP tools/list; execution not yet verified", "checked_at": timestamp()})
    return evidence


def _environment(profile: dict, arm_run: Path, arm: dict, router_model: str, phase: str, name: str) -> dict:
    names = list(profile["tools"]["environment_names"])
    for server in profile["tools"]["mcp_servers"].values():
        names.extend(server.get("env_vars", []))
        if server.get("bearer_token_env_var"):
            names.append(server["bearer_token_env_var"])
    environment = clean_environment(names=names)
    environment.update(CODEX_HOME=str(arm_run / "codex-home"), RIPPLETIDE_RUN_DIR=str(arm_run),
                       RIPPLETIDE_PROJECT_ROOT=arm["workspace"], RIPPLETIDE_RUN_ID=arm["run_id"],
                       RIPPLETIDE_PHASE=phase, RIPPLETIDE_MODEL=router_model,
                       RIPPLETIDE_HOOK_MODE="enforce" if name == "rippletide" else "observe")
    return environment


def _prepare_config(name: str, run: Path, manifest: dict, *, phase: str) -> dict:
    profile, arm = manifest["profile"], manifest["arms"][name]
    arm_run, workspace = run / name, Path(arm["workspace"])
    replacements = {"workspace": str(workspace), "run": str(arm_run)}
    tools = expand(profile["tools"], replacements)
    config = {"approval_policy": "never", "sandbox_mode": "workspace-write", "web_search": "disabled",
              "features": {"hooks": True}, "projects": {str(workspace): {"trust_level": "trusted"}},
              "mcp_servers": tools["mcp_servers"], "agents": {"max_threads": 3, **tools["agents"]}}
    if profile["model"]:
        config["model"] = profile["model"]
    if profile["effort"]:
        config["model_reasoning_effort"] = profile["effort"]
    if name == "rippletide":
        config["plugins"] = {"rippletide@personal": {"enabled": True}}
    else:
        config["plugins"] = {"rippletide@personal": {"enabled": False}}
        config["hooks"] = _hook_config(project_root() / "plugins/rippletide/scripts/guard.py")
    if phase == "preflight":
        config["mcp_servers"]["rippletide_uat_probe"] = {"command": sys.executable, "args": ["-m", "rippletide_uat.probe_server"], "enabled_tools": ["ping"]}
        if not tools["agents"]:
            definition = arm_run / "probe-agent.toml"
            definition.write_text('name = "rippletide_probe"\ndescription = "Read-only readiness check"\ndeveloper_instructions = "Return readiness only. Do not edit, use tools or delegate."\n')
            config["agents"]["rippletide_probe"] = {"description": "Read-only readiness check", "config_file": str(definition)}
    caps = native_capabilities() + arm.get("verified_capabilities", tools["capabilities"])
    for cap in caps:
        cap.setdefault("available", True)
    registry = {"version": 1, "registry_version": "paired-v1", "run_id": arm["run_id"],
                "variant": "D" if name == "rippletide" else "A", "phase": phase,
                "log_path": arm["router_events"], "preferences": tools["preferences"], "capabilities": caps}
    if name == "rippletide":
        require_workspace_path(workspace / ".rippletide/config.json", workspace)
        write_json(workspace / ".rippletide/config.json", registry)
    write_json(arm_run / f"{phase}-registry.json", registry)
    write_config(arm_run / "codex-home", config)
    shutil.copyfile(arm_run / "codex-home/config.toml", arm_run / f"{phase}-config.toml")
    arm["settings"]["tool_config_snapshot"] = str(arm_run / f"{phase}-config.toml")
    return config


def require_workspace_path(path: Path, workspace: Path) -> None:
    """Reject tracked symlinks that would redirect a harness mutation elsewhere."""
    if not path.resolve().is_relative_to(workspace.resolve()):
        raise ValueError(f"Harness configuration path escapes its disposable workspace: {path.name}")


def _suspend_project_configuration(workspace: Path, arm_run: Path) -> list[tuple[Path, Path]]:
    """Avoid user/project hook execution under the automation trust flag.

    Only these disposable worktree files are moved, and restored afterwards.
    Main repository configuration and working changes are never touched.
    """
    paths = [workspace / ".codex/config.toml", workspace / ".codex/hooks.json",
             workspace / ".codex/agents", workspace / ".rippletide/config.json"]
    # Validate all targets before moving any one of them.
    for path in paths:
        require_workspace_path(path, workspace)
    backups = []
    for path in paths:
        if path.exists():
            relative = path.relative_to(workspace)
            target = arm_run / "original-configuration" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
            backups.append((path, target))
    return backups


def _same_plugin_source(cached: Path, source: Path) -> bool:
    # Cachebuster versions and generated installation markers differ by design.
    # Compare all executable/runtime/skill dependencies, not just guard.py.
    relevant = ["scripts", "src", "skills", "hooks"]
    for folder in relevant:
        source_files = {file.relative_to(source) for file in (source / folder).rglob("*")
                        if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc"}
        cached_files = {file.relative_to(cached) for file in (cached / folder).rglob("*")
                        if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc"}
        if source_files != cached_files or any((source / file).read_bytes() != (cached / file).read_bytes() for file in source_files):
            return False
    return all((cached / name).is_file() and (cached / name).read_bytes() == (source / name).read_bytes()
               for name in ("pyproject.toml", "uv.lock", ".mcp.json"))


def _restore_project_configuration(backups: list[tuple[Path, Path]], arm_run: Path) -> None:
    generated_registry = arm_run / "workspace/.rippletide/config.json"
    require_workspace_path(generated_registry, arm_run / "workspace")
    for path, _ in backups:
        require_workspace_path(path, arm_run / "workspace")
    if generated_registry.exists():
        preserved = arm_run / "final-generated-configuration/.rippletide/config.json"
        preserved.parent.mkdir(parents=True, exist_ok=True)
        generated_registry.rename(preserved)
    for path, backup in backups:
        if path.exists():
            generated = arm_run / "final-generated-configuration" / path.relative_to(arm_run / "workspace")
            generated.parent.mkdir(parents=True, exist_ok=True)
            path.rename(generated)
        path.parent.mkdir(parents=True, exist_ok=True)
        backup.rename(path)


def completed_specialists(rollouts: list[str]) -> set[str]:
    verified = set()
    for rollout in rollouts:
        events = read_events(Path(rollout))
        metadata = next((event.get("payload", {}) for event in events if event.get("type") == "session_meta"), {})
        role = metadata.get("agent_role")
        if role and any(event.get("type") == "event_msg" and event.get("payload", {}).get("type") == "task_complete" for event in events):
            verified.add(role)
    return verified


def _status_payload(value) -> dict | None:
    if isinstance(value, str):
        try:
            return _status_payload(json.loads(value))
        except ValueError:
            return None
    if isinstance(value, dict):
        if "ready" in value and "model_identity" in value and "worker" in value:
            return value
        for key in ("structuredContent", "structured_content", "result", "content", "text"):
            result = _status_payload(value.get(key))
            if result is not None:
                return result
    if isinstance(value, list):
        for item in value:
            result = _status_payload(item)
            if result is not None:
                return result
    return None


def _mcp_output_success(value) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return False
    if not isinstance(value, dict):
        return False
    if value.get("error") or value.get("isError") or value.get("is_error"):
        return False
    if "result" in value:
        return _mcp_output_success(value["result"])
    return "content" in value or "structuredContent" in value or "structured_content" in value


def host_mcp_readiness(path: Path, calls: dict) -> dict:
    results = {server: {"status": "unavailable", "source": "actual host read-only preflight", "schema_source": "explicit profile (not tools/list)", "call_id": None}
               for server in calls}
    for event in read_events(path):
        if event.get("event") != "tool_completed" or event.get("phase") != "preflight":
            continue
        name = event.get("tool_name", "").split("__", 2)
        if len(name) != 3 or name[0] != "mcp" or name[1] not in calls:
            continue
        call = calls[name[1]]
        arguments = event.get("tool_input", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                continue
        if name[2] != call["tool"] or not isinstance(arguments, dict) or any(arguments.get(key) != value for key, value in call["arguments"].items()):
            continue
        if _mcp_output_success(event.get("tool_response")):
            results[name[1]].update(status="ready", call_id=event.get("call_id"), tool=call["tool"])
    return results


def baseline_contamination(workspace: Path) -> list[str]:
    found = []
    for folder in (".agents/skills", ".codex/skills"):
        for path in (workspace / folder).rglob("SKILL.md"):
            if not path.resolve().is_relative_to(workspace.resolve()):
                found.append(path.relative_to(workspace).as_posix())
                continue
            text = path.read_text()
            if (path.parent.name == "route-capabilities" or "mcp__rippletide__route" in text
                    or re.search(r"(?is)rippletide.{0,80}route-capabilities", text)):
                found.append(path.relative_to(workspace).as_posix())
    return found


def model_readiness(hooks: Path, model: str, workspace: Path) -> dict:
    statuses = []
    for event in read_events(hooks):
        name = event.get("tool_name", "")
        request = event.get("tool_input", {})
        if not (event.get("event") == "tool_completed" and event.get("phase") == "preflight"
                and "rippletide" in name and (name.endswith("__status") or name.endswith(".status"))):
            continue
        if isinstance(request, str):
            try:
                request = json.loads(request)
            except ValueError:
                continue
        if request.get("project_root") != str(workspace):
            continue
        payload = _status_payload(event.get("tool_response"))
        if payload:
            statuses.append(payload)
    result = statuses[-1] if statuses else {}
    return {"ready": bool(result.get("ready") and result.get("worker", {}).get("ready")
                           and result.get("model_identity", {}).get("model") == model),
            "requested_model": model, "observed_status": result or None,
            "source": "actual host rippletide.status execution"}


def _preflight(name: str, run: Path, manifest: dict, codex: Path, timeout: float, cancel: threading.Event) -> None:
    arm, profile = manifest["arms"][name], manifest["profile"]
    arm_run, workspace = run / name, Path(arm["workspace"])
    config = _prepare_config(name, run, manifest, phase="preflight")
    environment = _environment(profile, arm_run, arm, manifest["router_model"], "preflight", name)
    tool_profile = expand(profile["tools"], {"workspace": str(workspace), "run": str(arm_run)})
    if name == "baseline" and (contamination := baseline_contamination(workspace)):
        arm["baseline_contamination"] = contamination
        raise ValueError("Project contains a routing skill that would contaminate Codex-alone; use a source without that skill")
    host_probes = tool_profile["mcp_preflight"]
    direct_servers = {key: value for key, value in tool_profile["mcp_servers"].items() if key not in host_probes}
    arm["capability_preflight"] = asyncio.run(probe_capabilities(direct_servers, tool_profile["capabilities"], environment))
    if not authenticated(codex, arm_run / "codex-home", environment):
        raise ValueError("Private Codex profile has no recognized authentication")
    if name == "rippletide":
        result = subprocess.run([str(codex), "plugin", "add", "rippletide@personal"], cwd=arm_run / "codex-home",
                                env=environment, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError("Private installation failed; stage the current personal plugin first")
        guards = list((arm_run / "codex-home/plugins/cache").glob("**/rippletide/*/scripts/guard.py"))
        if not guards or any(not _same_plugin_source(path.parent.parent, project_root() / "plugins/rippletide") for path in guards):
            raise ValueError("Installed plugin source differs from this checkout; reinstall the current source")
    catalog = _json_command([str(codex), "mcp", "list", "--json"], cwd=workspace, environment=environment)
    actual = {entry["name"] for entry in catalog if entry.get("enabled", True)}
    expected_names = set(config["mcp_servers"]) | ({"rippletide"} if name == "rippletide" else set())
    if actual != expected_names:
        raise ValueError("Private MCP catalog differs from the approved profile; task not started")
    roles = [key for key in config["agents"] if key != "max_threads"]
    prompt = ("Host setup verification only; not a task attempt. Run the native shell command `printf rippletide-ready`. "
              "Call rippletide_uat_probe.ping once. Invoke each named specialist " + ", ".join(roles) +
              " with the read-only assignment 'Return your configured role only; no tool calls, edits or further delegation.' "
              "Wait for their actual results. Do not search files or solve the user task. " +
              ("Also execute these explicitly authorized read-only provider readiness calls, without changing the arguments: " +
               json.dumps(host_probes, sort_keys=True) + ". " if host_probes else "") +
              (f"Finally call rippletide.status with project_root={workspace} and report readiness. If the worker is still warming, wait and retry status at most twice. " if name == "rippletide" else ""))
    preflight = arm_run / "preflight"
    preflight.mkdir()
    result = capture_session(codex, home=arm_run / "codex-home", workspace=workspace, run=preflight,
                             environment=environment, prompt=prompt, timeout=timeout, cancel=cancel)
    arm["preflight"] = result
    if result["status"] != "completed":
        raise ValueError("Host hook preflight did not complete")
    proof = _json_command([sys.executable, str(project_root() / "plugins/rippletide/scripts/guard.py"),
                           "--check-events", arm["hook_events"]], cwd=arm_run, environment=environment)
    arm["hook_preflight"] = proof
    if not proof.get("ready"):
        raise ValueError("Native, MCP and specialist hook coverage was not proved; task not started")
    completed = completed_specialists(result["child_rollouts"])
    arm["specialist_preflight"] = {"requested": roles, "completed": sorted(completed), "ready": set(roles) <= completed}
    if not set(roles) <= completed:
        raise ValueError("Not every registered specialist has a completed real child session")
    hosted = host_mcp_readiness(Path(arm["hook_events"]), host_probes)
    arm["capability_preflight"].update(hosted)
    if any(value["status"] != "ready" for value in hosted.values()):
        raise ValueError("An approved provider read-only call was not verified through Codex; no task launched")
    for cap in tool_profile["capabilities"]:
        server = cap["invocation"].get("server")
        if cap["kind"] == "mcp" and server in hosted:
            cap.update(available=True, availability=hosted[server])
    if name == "rippletide":
        arm["model_preflight"] = model_readiness(Path(arm["hook_events"]), manifest["router_model"], workspace)
        if not arm["model_preflight"]["ready"]:
            raise ValueError("Requested routing model was not ready in actual installed MCP status; task not started")
    arm["verified_capabilities"] = tool_profile["capabilities"]


def _exhausted(path: Path) -> str | None:
    # Ignore a partially written last line while another process appends.
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("phase") == "task" and event.get("exhausted"):
            return "routing_correction_budget_exhausted"
    return None


def _run_task(name: str, run: Path, manifest: dict, codex: Path, timeout: float, cancel: threading.Event,
              barrier: threading.Barrier | None) -> None:
    arm, profile = manifest["arms"][name], manifest["profile"]
    arm_run, workspace = run / name, Path(arm["workspace"])
    _prepare_config(name, run, manifest, phase="task")
    environment = _environment(profile, arm_run, arm, manifest["router_model"], "task", name)
    if barrier:
        barrier.wait(timeout=30)
    arm["status"] = "running"
    arm["interventions"].append({"category": "planned_prompt", "timestamp": timestamp(), "description": "Initial task prompt"})
    prompt = (TASK_BOUNDARY + "\nProject tool preferences (apply equally to both arms):\n" +
              json.dumps(profile["tools"]["preferences"], sort_keys=True) + "\nTask:\n" + manifest["prompt"])
    result = capture_session(codex, home=arm_run / "codex-home", workspace=workspace, run=arm_run,
                             environment=environment, prompt=prompt,
                             timeout=timeout, cancel=cancel, stop_check=lambda: _exhausted(Path(arm["hook_events"])))
    arm.update(result)
    arm["interventions_complete"] = True


def _acceptance(name: str, run: Path, manifest: dict, timeout: float, cancel: threading.Event) -> None:
    arm, profile = manifest["arms"][name], manifest["profile"]
    arm_run, workspace = run / name, Path(arm["workspace"])
    # Graders use only clean system environment; provider credentials are never
    # given to tests and evaluations cannot affect the timed task phase.
    environment = clean_environment()
    environment.pop("CODEX_API_KEY", None)
    for index, check in enumerate(profile["frozen_checks"]):
        command = expand(check["argv"], {"workspace": str(workspace), "run": str(arm_run)})
        result = run_process(command, cwd=workspace, environment=environment,
                             output=arm_run / f"acceptance-{index}", timeout=timeout, cancel=cancel)
        if result["status"] == "completed":
            result["status"] = "passed"
        arm["acceptance"].append({**result, "independence": check["independence"], "phase": "acceptance"})
    arm["acceptance_status"] = ("ungraded" if not arm["acceptance"] else
                                 "passed" if all(check["status"] == "passed" for check in arm["acceptance"]) else "failed")
    patch = subprocess.check_output(["git", "-C", str(workspace), "diff", "--binary", manifest["base_sha"]])
    (arm_run / "changes.patch").write_bytes(patch)
    arm["patch"] = str(arm_run / "changes.patch")
    arm["git_status"] = subprocess.check_output(["git", "-C", str(workspace), "status", "--porcelain=v1"], text=True)
    untracked = subprocess.check_output(["git", "-C", str(workspace), "ls-files", "--others", "--exclude-standard", "-z"]).decode().split("\0")
    arm["untracked_files"] = []
    for relative in filter(None, untracked):
        source = workspace / relative
        if source.is_symlink() or not source.resolve().is_relative_to(workspace.resolve()) or not source.is_file():
            arm["untracked_files"].append({"path": relative, "status": "not_copied", "reason": "nonregular_or_symlink"})
            continue
        destination = arm_run / "untracked-source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        arm["untracked_files"].append({"path": relative, "status": "archived", "artifact": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})


def execute_pair(run: Path, manifest: dict, *, codex: Path | None = None, timeout: float = 600,
                 preflight_timeout: float = 180, check_timeout: float = 180, judge: bool = True,
                 reverse: bool = False) -> dict:
    codex = (codex or pinned_codex()).absolute()
    links, suspended = {}, {}
    cancel = threading.Event()

    def save():
        write_json(run / "pair.json", manifest)

    try:
        version = verify_codex(codex)
        manifest["codex_version"] = version
        for name in ARMS:
            arm, arm_run = manifest["arms"][name], run / name
            arm["settings"]["codex_version"] = version
            suspended[name] = _suspend_project_configuration(Path(arm["workspace"]), arm_run)
            home = arm_run / "codex-home"
            home.mkdir(mode=0o700)
            links[name] = link_auth(home)
            environment = _environment(manifest["profile"], arm_run, arm, manifest["router_model"], "setup", name)
            arm["bootstrap"] = []
            for index, command in enumerate(manifest["profile"]["bootstrap"]):
                command = expand(command, {"workspace": arm["workspace"], "run": str(arm_run)})
                result = run_process(command, cwd=Path(arm["workspace"]), environment=environment,
                                     output=arm_run / f"bootstrap-{index}", timeout=check_timeout, cancel=cancel)
                arm["bootstrap"].append(result)
                if result["status"] != "completed":
                    raise ValueError(f"{name} dependency bootstrap failed")
            _preflight(name, run, manifest, codex, preflight_timeout, cancel)
            arm["status"] = "ready"
            save()
        manifest["status"] = "running"
        manifest["task_started_at"] = timestamp()
        save()
        order = list(reversed(ARMS)) if reverse else list(ARMS)
        if manifest["mode"] == "parallel":
            barrier = threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_run_task, name, run, manifest, codex, timeout, cancel, barrier) for name in order]
                try:
                    for future in futures:
                        future.result()
                except BaseException:
                    cancel.set()
                    barrier.abort()
                    raise
        else:
            for name in order:
                _run_task(name, run, manifest, codex, timeout, cancel, None)
        manifest["task_finished_at"] = timestamp()
        observed = [manifest["arms"][name].get("observed_settings", []) for name in ARMS]
        manifest["observed_settings_match"] = bool(observed[0] and observed[0] == observed[1])
        if not manifest["observed_settings_match"]:
            manifest["comparison_warning"] = "Actual Codex model/settings equality was not established; do not attribute differences solely to routing"
        save()
        for name in ARMS:
            _restore_project_configuration(suspended.get(name, []), run / name)
            suspended.pop(name, None)
        for name in ARMS:
            _acceptance(name, run, manifest, check_timeout, cancel)
        manifest["status"] = "completed" if all(arm["status"] == "completed" for arm in manifest["arms"].values()) else "failed"
    except KeyboardInterrupt:
        cancel.set()
        manifest["status"] = "cancelled"
        for arm in manifest["arms"].values():
            if arm["status"] in {"ready", "running", "setup-blocked"}:
                arm["status"] = "cancelled"
    except Exception as exc:
        cancel.set()
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        manifest["status"] = "failed" if manifest.get("task_started_at") else "setup-blocked"
        for arm in manifest["arms"].values():
            if arm["status"] in {"ready", "running"}:
                arm["status"] = manifest["status"]
    finally:
        for name, link in links.items():
            try:
                unlink_auth(link)
            except (OSError, RuntimeError) as exc:
                # Preserve altered credentials, but never let one damaged link
                # prevent cleanup of the other arm or retention of the report.
                manifest.setdefault("cleanup_errors", {})[f"{name}_authentication"] = str(exc)
                manifest["status"] = "failed"
        for name, backups in suspended.items():
            try:
                _restore_project_configuration(backups, run / name)
            except (OSError, ValueError) as exc:
                manifest.setdefault("cleanup_errors", {})[name] = str(exc)
                manifest["status"] = "failed"
        manifest["finished_at"] = timestamp()
        save()
    if judge and any(arm["session_path"] for arm in manifest["arms"].values()):
        from .correctness import grade_pair
        judge_home = run / "judge-home"
        judge_home.mkdir(mode=0o700)
        link = link_auth(judge_home)
        environment = clean_environment(names=["RIPPLETIDE_JUDGE_MAX_CHOICES", "RIPPLETIDE_JUDGE_CONCURRENCY"])
        environment["CODEX_HOME"] = str(judge_home)
        try:
            grade_pair(run, codex=str(codex), environment=environment,
                       model=manifest["profile"]["model"], effort=manifest["profile"]["effort"], timeout=check_timeout)
        finally:
            try:
                unlink_auth(link)
            except (OSError, RuntimeError) as exc:
                manifest.setdefault("cleanup_errors", {})["judge_authentication"] = str(exc)
                manifest["status"] = "failed"
                save()
    from .paired_evidence import report_pair
    return report_pair(run)


def run_pairs(repo: Path, prompt: str, *, base: str = "main", router_model: str = "qwen25-rlcd",
              mode: str = "parallel", repeat: int = 1, output_root: Path | None = None,
              codex: Path | None = None, timeout: float = 600, preflight_timeout: float = 180,
              check_timeout: float = 180, judge: bool = True) -> dict:
    if not 1 <= repeat <= 100:
        raise ValueError("repeat must be between 1 and 100")
    if min(timeout, preflight_timeout, check_timeout) <= 0:
        raise ValueError("All phase timeouts must be positive")
    # Freeze the base once for the whole repeated comparison, even if main
    # advances while the experiment is running.
    root = repo_root(repo)
    sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--verify", f"{base}^{{commit}}"], text=True).strip()
    runs = []
    for index in range(repeat):
        run, manifest = prepare_pair(root, prompt, base=sha, router_model=router_model, mode=mode, output_root=output_root)
        manifest.update(base=base, repetition=index + 1, repeat=repeat)
        execute_pair(run, manifest, codex=codex, timeout=timeout, preflight_timeout=preflight_timeout,
                     check_timeout=check_timeout, judge=judge, reverse=index % 2 == 1)
        runs.append({"run": str(run), "status": manifest["status"], "report": str(run / "report.html"),
                     "acceptance_status": {name: arm.get("acceptance_status", "not_run") for name, arm in manifest["arms"].items()}})
        if manifest["status"] in {"cancelled", "setup-blocked"}:
            break
    return {"runs": runs, "mode": mode, "base_sha": sha, "router_model": router_model,
            "benchmark_validated": False, "note": "Task completion, tool correctness and routing compliance are separate report dimensions."}
