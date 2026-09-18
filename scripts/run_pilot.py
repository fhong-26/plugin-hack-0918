#!/usr/bin/env python3
"""Run one fresh local UAT attempt through public CLIs; never grade by agent claims."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import tomllib


REPO = Path(__file__).resolve().parents[1]
INSTALLED_PLUGIN_SOURCES = [
    "https://github.com/openai/codex/blob/rust-v0.132.0/codex-rs/core-plugins/src/loader.rs#L351-L358",
    "https://github.com/openai/codex/blob/rust-v0.132.0/codex-rs/config/src/state.rs#L290-L307",
]


def isolated_environment(isolated_home):
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(isolated_home)
    return environment


def write_user_config(isolated_home, config):
    path = isolated_home / "config.toml"
    path.write_text("\n".join(f"{key}={toml_value(value)}" for key, value in config.items()) + "\n")
    path.chmod(0o600)
    return path


def text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from text_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)


def installed_plugin_preflight(codex, codex_version, output_root):
    """Install/discover only Rippletide in a private User-layer configuration.

    CLI 0.132 ignores CLI/project plugin enablement, so use its published install
    workflow with a minimal User layer. Never load or modify personal config.
    """
    isolated_home = Path(tempfile.mkdtemp(prefix="rippletide-codex-"))
    isolated_home.chmod(0o700)
    result = {"status": "blocked", "plugin_mode": "installed",
              "codex_version": codex_version, "isolated_codex_home": str(isolated_home),
              "task_attempted": False, "model_called": False,
              "benchmark_validated": False, "sources": INSTALLED_PLUGIN_SOURCES,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "isolation": {"private_user_layer": True, "home_mode": "0700",
                            "personal_config_loaded": False, "personal_services_enabled": False,
                            "model_override": False}}
    environment = isolated_environment(isolated_home)
    write_user_config(isolated_home, {"plugins": {"rippletide@personal": {"enabled": True}}})
    try:
        # The existing personal marketplace is implicitly discovered; do not add
        # a marketplace or change the approved source/global installation.
        _, result["installation"] = run_cli([codex, "plugin", "add", "rippletide@personal"],
                                            cwd=isolated_home, env=environment, timeout=120)
        _, servers = run_cli([codex, "mcp", "list", "--json"], cwd=isolated_home,
                             env=environment, timeout=60)
        if not isinstance(servers, list) or {entry.get("name") for entry in servers} != {"rippletide"}:
            raise ValueError("Isolated preflight must discover only the installed rippletide MCP server")
        result["mcp_servers"] = servers
        _, prompt = run_cli([codex, "debug", "prompt-input", "Installed-plugin discovery preflight only"],
                            cwd=isolated_home, env=environment, timeout=60)
        entries = [line for value in text_values(prompt) for line in value.splitlines()
                   if line.startswith("- rippletide:route-capabilities:")]
        if len(entries) != 1 or str(isolated_home / "plugins" / "cache") not in entries[0]:
            raise ValueError("Namespaced installed routing skill was not discovered from the isolated cache")
        result.update(status="ready", installed_skill=entries[0],
                      note="Discovery only; no task or routing execution has happened yet.")
    except Exception as exc:
        result.update(reason_code="ISOLATED_PLUGIN_PREFLIGHT_FAILED", error=f"{type(exc).__name__}: {exc}")
    output_root.mkdir(parents=True, exist_ok=True)
    diagnostic = output_root / ("installed-plugin-preflight-"
                               + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with diagnostic.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    result["evidence"] = str(diagnostic)
    return result


def link_auth_if_needed(isolated_home):
    """Reuse credentials by reference only; never read/copy/print their contents."""
    # Codex exec accepts CODEX_API_KEY. OPENAI_API_KEY alone is not proof that
    # this host will send a bearer token; the first isolated attempt confirmed
    # that treating it as sufficient can silently skip required stored auth.
    if os.environ.get("CODEX_API_KEY"):
        return None
    source_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    source = source_home / "auth.json"
    if not source.is_file():
        return None  # Other supported authentication may exist; host reports failures.
    target = isolated_home / "auth.json"
    target.symlink_to(source.resolve())
    return (target, source.resolve())


def isolated_authentication_ready(codex, isolated_home):
    # Login status may include a key hint. Retain only its success/failure code.
    result = subprocess.run([codex, "login", "status"], cwd=isolated_home,
                            env=isolated_environment(isolated_home),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=30)
    return result.returncode == 0


def remove_auth_link(link):
    if link is not None:
        target, source = link
        if not target.is_symlink() or target.readlink() != source:
            raise RuntimeError("Temporary auth link changed; refusing to remove a different target")
        target.unlink()  # Remove only our exact symlink, never its credential target.


def installed_session_config(workspace, run, isolated_home, label):
    archive = run / "installed-plugin-metadata" / workspace.name
    archive.mkdir(parents=True, exist_ok=True)
    original = archive / "development-config.toml"
    if not original.exists():
        (workspace / ".codex" / "config.toml").rename(original)
    skill = workspace / ".agents" / "skills" / "route-capabilities"
    if skill.exists():
        skill.rename(archive / "development-skill")
    fixture = tomllib.loads(original.read_text())
    servers = fixture.get("mcp_servers", {})
    servers.pop("rippletide", None)
    if set(servers) - {"uat_docs", "uat_tracker", "uat_semantic"}:
        raise ValueError("Installed UAT configuration contains an unexpected MCP service")
    phase = "preflight" if label == "agent-preflight" else "task"
    for name, server in servers.items():
        if name in {"uat_docs", "uat_tracker"}:
            server.setdefault("env", {})["RIPPLETIDE_UAT_PHASE"] = phase
    config = {"plugins": {"rippletide@personal": {"enabled": True}},
              "agents": fixture.get("agents", {}), "mcp_servers": servers,
              "approval_policy": "never", "sandbox_mode": "workspace-write",
              "projects": {str(REPO): {"trust_level": "trusted"},
                           str(workspace): {"trust_level": "trusted"}}}
    path = write_user_config(isolated_home, config)
    snapshot = archive / f"{label}-user-config.toml"
    shutil.copyfile(path, snapshot)
    return snapshot


def toml_value(value):
    """Encode the JSON-like subset used by generated fixture configuration."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(key)}={toml_value(item)}" for key, item in value.items()) + "}"
    raise TypeError(f"Unsupported config value: {type(value).__name__}")


def read_events(path):
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def run_cli(arguments, *, cwd=REPO, require_success=True, env=None, timeout=None):
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout)
    if require_success and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {arguments}\n{result.stderr}\n{result.stdout}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"stdout": result.stdout, "stderr": result.stderr}
    return result.returncode, payload


def capture_session(codex, workspace, run, label, prompt, timeout, resume=None, *, installed_plugin=False,
                    isolated_home=None):
    if installed_plugin and isolated_home is None:
        raise ValueError("Installed-plugin isolation requires a preflighted private home")
    command = [codex, "exec", "--skip-git-repo-check", "--json",
               "--sandbox", "workspace-write", "-c", 'approval_policy="never"']
    environment = None
    config_snapshot = None
    if installed_plugin:
        environment = isolated_environment(isolated_home)
        environment["RIPPLETIDE_PHASE"] = "preflight" if label == "agent-preflight" else "task"
        config_snapshot = installed_session_config(workspace, run, isolated_home, label)
    else:
        command.append("--ignore-user-config")
        command.extend(["-c", 'plugins."rippletide@personal".enabled=false'])
    # Config discovery depends on process cwd in some CLI versions, not only -C.
    for root in (REPO, workspace):
        command.extend(["-c", f"projects.{json.dumps(str(root))}.trust_level=\"trusted\""])
    # On CLI 0.132, --ignore-user-config also excludes project config layers.
    # Explicit overrides isolate the test from personal services without losing
    # the prepared fixture's real servers or named-agent registrations.
    config = {} if installed_plugin else tomllib.loads((workspace / ".codex" / "config.toml").read_text())
    phase = "preflight" if label == "agent-preflight" else "task"
    for name, server in config.get("mcp_servers", {}).items():
        if name in {"rippletide", "uat_docs", "uat_tracker"}:
            server.setdefault("env", {})["RIPPLETIDE_PHASE" if name == "rippletide" else "RIPPLETIDE_UAT_PHASE"] = phase
    for key in ("agents", "mcp_servers", "marketplaces", "plugins", "skills"):
        if key in config:
            command.extend(["-c", f"{key}={toml_value(config[key])}"])
    if resume:
        command.extend(["resume", resume, "-"])
    else:
        command.append("-")
    output = run / f"{label}.jsonl"
    errors = run / f"{label}.stderr.log"
    started = time.monotonic()
    with output.open("x") as stdout, errors.open("x") as stderr:
        child = subprocess.Popen(command, cwd=workspace, stdin=subprocess.PIPE,
                                 stdout=stdout, stderr=stderr, text=True,
                                 start_new_session=True, env=environment)
        timed_out = False
        try:
            child.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    events = read_events(output)
    thread = next((event.get("thread_id") for event in events if event.get("type") == "thread.started"), resume)
    raw = None
    child_rollouts = []
    if thread:
        codex_home = isolated_home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        matches = list((codex_home / "sessions").rglob(f"*{thread}*.jsonl"))
        if len(matches) == 1:
            raw = run / f"{label}.raw.jsonl"
            shutil.copyfile(matches[0], raw)
            # Preserve actual specialist evidence without summing copied parent
            # history into child usage. Cost remains parent-only until a host-
            # aware incremental-usage aggregator is available.
            children = set()
            for event in read_events(raw):
                payload = event.get("payload", {})
                if payload.get("type") != "function_call_output":
                    continue
                try:
                    value = json.loads(payload.get("output", ""))
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(value, dict) and isinstance(value.get("agent_id"), str):
                    children.add(value["agent_id"])
            for child_id in children:
                sources = list((codex_home / "sessions").rglob(f"*{child_id}*.jsonl"))
                if len(sources) == 1:
                    destination = run / f"{label}.child-{child_id}.jsonl"
                    shutil.copyfile(sources[0], destination)
                    child_rollouts.append(str(destination))
    return {"label": label, "thread_id": thread, "exit_code": child.returncode,
            "timed_out": timed_out, "elapsed_seconds": round(time.monotonic() - started, 3),
            "events": str(output), "raw_events": str(raw) if raw else None,
            "child_raw_events": child_rollouts, "usage_scope": "parent_only",
            "stderr": str(errors), "command": command,
            "isolated_codex_home": str(isolated_home) if installed_plugin else None,
            "effective_user_config": str(config_snapshot) if config_snapshot else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=[f"U{i:02}" for i in range(1, 10)])
    parser.add_argument("--variant", default="D", choices=list("ABCD"))
    parser.add_argument("--failure", choices=["docs", "tracker", "reviewer", "test_specialist", "model"])
    parser.add_argument("--comparison-scenario", choices=["U02", "U05"], default="U02")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--installed-plugin", action="store_true", help="Install/test the plugin in a private Codex User configuration (D only)")
    parser.add_argument("--agents", action="store_true", help="Preflight both real specialist roles even for a non-agent scenario")
    parser.add_argument("--no-followup", action="store_true")
    parser.add_argument("--timeout", type=int, default=600, help="Per-session seconds; stalled attempts are retained")
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--output-root", type=Path, default=REPO / ".uat-runs")
    args = parser.parse_args()
    uv = shutil.which("uv")
    if not uv or not args.codex:
        parser.error("uv and codex are required")
    if args.installed_plugin and args.variant != "D":
        parser.error("--installed-plugin is a separate variant D packaging smoke, not an A-D comparison")
    codex_version = subprocess.check_output([args.codex, "--version"], text=True).strip()
    isolation = None
    auth_link = None
    try:
        if args.installed_plugin:
            isolation = installed_plugin_preflight(args.codex, codex_version, args.output_root.resolve())
            if isolation["status"] == "ready":
                isolated_home = Path(isolation["isolated_codex_home"])
                auth_link = link_auth_if_needed(isolated_home)
                isolation["authentication_ready"] = isolated_authentication_ready(args.codex, isolated_home)
                isolation["temporary_auth_link"] = auth_link is not None
                if not isolation["authentication_ready"]:
                    isolation.update(status="blocked", reason_code="ISOLATED_AUTHENTICATION_UNAVAILABLE",
                                     error="Private host has no recognized authentication; no task started.")
                Path(isolation["evidence"]).write_text(json.dumps(isolation, indent=2) + "\n")
            print(json.dumps({"event": "installed_plugin_preflight", **isolation}), flush=True)
            if isolation["status"] != "ready":
                return 2
        return run_prepared_pilot(args, uv, codex_version, isolation)
    finally:
        remove_auth_link(auth_link)
        if isolation and isolation.get("evidence"):
            isolation["auth_link_cleanup"] = "removed" if auth_link is not None else "not_needed"
            isolation["auth_link_cleanup_at"] = datetime.now(timezone.utc).isoformat()
            Path(isolation["evidence"]).write_text(json.dumps(isolation, indent=2) + "\n")


def run_prepared_pilot(args, uv, codex_version, isolation=None):
    isolated_home = Path(isolation["isolated_codex_home"]) if isolation else None
    uat = [uv, "run", "--locked", "--project", str(REPO / "user_tests"), "rippletide-uat"]
    prepare = [*uat, "prepare", "--scenario", args.scenario, "--variant", args.variant,
               "--output-root", str(args.output_root.resolve()),
               "--comparison-scenario", args.comparison_scenario]
    if args.failure:
        prepare.extend(["--failure", args.failure])
    _, prepared = run_cli(prepare)
    run, workspace = Path(prepared["run"]), Path(prepared["workspace"])
    print(json.dumps({"event": "prepared", "run": str(run), "workspace": str(workspace)}), flush=True)
    result = {"run": str(run), "created_at": datetime.now(timezone.utc).isoformat(),
              "codex_version": codex_version,
              "plugin_mode": "installed" if args.installed_plugin else "development",
              "installed_plugin_preflight": isolation,
              "sessions": [], "status": "running", "benchmark_validated": False}

    def save():
        (run / "pilot-run.json").write_text(json.dumps(result, indent=2) + "\n")

    def interaction(category, description):
        run_cli([*uat, "intervention", "--run", str(run), "--category", category, "--description", description])

    save()
    try:
        if args.semantic:
            _, result["semantic"] = run_cli([*uat, "prepare-semantic", "--run", str(run)], require_success=False)
        needs_agents = (args.agents or args.scenario in {"U04", "U05", "U07"}
                        or (args.scenario == "U09" and args.comparison_scenario == "U05"))
        if needs_agents:
            interaction("setup", "Preflight real named agents before the task; not routing evidence")
            setup = capture_session(args.codex, workspace, run, "agent-preflight",
                                    Path(prepared["agent_preflight_prompt"]).read_text(), args.timeout,
                                    installed_plugin=args.installed_plugin, isolated_home=isolated_home)
            result["sessions"].append(setup)
            evidence = setup["raw_events"] or setup["events"]
            _, result["agents"] = run_cli([*uat, "verify-agents", "--run", str(run), "--session", evidence], require_success=False)
            save()
            print(json.dumps({"event": "agents_checked", "result": result["agents"]}), flush=True)
        interaction("planned_prompt", "Initial scenario prompt")
        first = capture_session(args.codex, workspace, run, "session", prepared["prompt"], args.timeout,
                                installed_plugin=args.installed_plugin, isolated_home=isolated_home)
        result["sessions"].append(first)
        save()
        print(json.dumps({"event": "task_finished", "thread_id": first["thread_id"],
                          "exit_code": first["exit_code"], "elapsed_seconds": first["elapsed_seconds"]}), flush=True)
        final = first
        manifest = json.loads((run / "run.json").read_text())
        if manifest.get("secondary_workspace") and first["exit_code"] == 0:
            interaction("planned_prompt", "Repeat the investigation in the second project with different saved preferences")
            second = capture_session(args.codex, Path(manifest["secondary_workspace"]), run,
                                     "secondary-session", prepared["prompt"], args.timeout,
                                     installed_plugin=args.installed_plugin, isolated_home=isolated_home)
            result["sessions"].append(second)
            save()
        if prepared.get("followup") and not args.no_followup and first["exit_code"] == 0 and first["thread_id"]:
            if args.scenario == "U01":
                _, result["starter_check"] = run_cli([*uat, "check", "--run", str(run), "--stage", "starter"], require_success=False)
            interaction("planned_prompt", "Planned scenario follow-up")
            final = capture_session(args.codex, workspace, run, "followup", prepared["followup"], args.timeout, first["thread_id"],
                                    installed_plugin=args.installed_plugin, isolated_home=isolated_home)
            result["sessions"].append(final)
        evidence = final["raw_events"] or final["events"]
        _, result["check"] = run_cli([*uat, "check", "--run", str(run)], require_success=False)
        _, result["report"] = run_cli([*uat, "report", "--run", str(run), "--session", evidence], require_success=False)
        result["status"] = "needs_evidence_review"
        if any(item["timed_out"] for item in result["sessions"]):
            result["status"] = "stalled"
        elif any(item["exit_code"] for item in result["sessions"]):
            result["status"] = "failed"
        result["note"] = "Review scenario assertions, then use rippletide-uat record-check/finalize. CLI exit success is not task success."
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        save()
    print(json.dumps({"event": "pilot_result", "run": str(run), "status": result["status"],
                      "check": result.get("check"), "error": result.get("error")}), flush=True)
    return 1 if result["status"] in {"failed", "stalled"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
