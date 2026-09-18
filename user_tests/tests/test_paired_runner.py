from __future__ import annotations

import json
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading
import signal
import time

import pytest

from rippletide_uat.cli import parser
from rippletide_uat import paired
from rippletide_uat.paired_host import (clean_environment, collect_rollouts, link_auth,
                                       run_process, terminate_owned, unlink_auth, write_config)
from rippletide_uat.profiles import (argv_value, configure, load_profile, profile_path,
                                    validate_tool_config)
from rippletide_uat.storage import read_json, write_json


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLETIDE_UAT_DATA_DIR", str(tmp_path / "private-data"))
    path = tmp_path / "source"
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "fixture@example.invalid"], check=True)
    (path / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(path), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "fixture"], check=True, capture_output=True)
    return path


def test_configure_private_defaults_and_explicit_replacement(repo):
    result = configure(repo)
    profile = Path(result["profile"])
    assert not profile.is_relative_to(repo)
    if os.name != "nt":
        assert profile.stat().st_mode & 0o777 == 0o600
    assert result["acceptance"] == "ungraded"
    assert not result["tools"]["mcp_servers"]
    assert set(result["tools"]["agents"]) == {"rippletide_reviewer", "rippletide_test_specialist"}
    with pytest.raises(FileExistsError):
        configure(repo)
    configure(repo, checks=[["python", "-m", "pytest"]], replace=True)
    assert load_profile(repo)["checks"] == [["python", "-m", "pytest"]]


def test_profile_rejects_secret_fields_and_unapproved_provider_tools():
    server = {"url": "https://example.invalid/mcp", "enabled_tools": ["get_issue"]}
    with pytest.raises(ValueError, match="inline-secret"):
        validate_tool_config({"mcp_servers": {"tracker": {**server, "http_headers": {"Authorization": "secret"}}}})
    with pytest.raises(ValueError, match="embedded credentials"):
        validate_tool_config({"mcp_servers": {"tracker": {**server, "url": "https://secret@example.invalid/mcp"}}})
    with pytest.raises(ValueError, match="allowlist"):
        validate_tool_config({"mcp_servers": {"tracker": {"url": server["url"]}}})
    with pytest.raises(ValueError, match="explicitly enabled"):
        validate_tool_config({"mcp_servers": {"tracker": server}, "capabilities": [{"id": "mcp.ticket", "kind": "mcp", "operations": ["knowledge_lookup"], "description": "Ticket", "input_schema": {}, "invocation": {"server": "tracker", "tool": "update_issue"}}]})
    result = validate_tool_config({"mcp_servers": {"tracker": {**server, "bearer_token_env_var": "TRACKER_TOKEN"}}})
    assert result["mcp_servers"]["tracker"]["bearer_token_env_var"] == "TRACKER_TOKEN"


def test_specialists_must_inherit_model_settings(tmp_path):
    definition = tmp_path / "specialist.toml"
    definition.write_text('model="some-model"\ndeveloper_instructions="read only"\n')
    with pytest.raises(ValueError, match="inherit"):
        validate_tool_config({"agents": {"review": {"description": "review", "config_file": str(definition)}}})


def test_json_argv_not_shell():
    assert argv_value('["python", "-m", "pytest"]') == ["python", "-m", "pytest"]
    for value in ('"pytest; echo bad"', "[]", '["pytest",1]'):
        with pytest.raises(ValueError):
            argv_value(value)


def test_fresh_pair_same_frozen_sha_preserves_dirty_source(repo):
    configure(repo)
    before = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    (repo / "app.py").write_text("user change\n")
    run, manifest = paired.prepare_pair(repo, "Fix the boundary")
    assert manifest["base_sha"] == before
    assert manifest["router_model"] == "qwen25-rlcd"
    for arm in manifest["arms"].values():
        assert (Path(arm["workspace"]) / "app.py").read_text() == "value = 1\n"
        assert arm["base_sha"] == before
        assert arm["acceptance"] == []
        assert arm["status"] == "setup-blocked"
    assert (repo / "app.py").read_text() == "user change\n"
    assert subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip() == "main"
    second, _ = paired.prepare_pair(repo, "Fix the boundary")
    assert second != run and run.exists()


def test_output_must_not_be_inside_source(repo):
    configure(repo)
    with pytest.raises(ValueError, match="outside"):
        paired.prepare_pair(repo, "Task", output_root=repo / "logs")


def test_freeze_independent_grader_outside_presented_workspaces(repo, tmp_path):
    grader = tmp_path / "grader.py"
    grader.write_text("assert True\n")
    configure(repo, independent_checks=[[sys.executable, str(grader), "{workspace}"]])
    run, manifest = paired.prepare_pair(repo, "Task")
    check = manifest["profile"]["frozen_checks"][0]
    assert check["independence"] == "external"
    frozen = Path(check["argv"][1])
    grader.write_text("assert False\n")
    assert frozen.read_text() == "assert True\n"
    assert not any(frozen.is_relative_to(Path(arm["workspace"])) for arm in manifest["arms"].values())


def test_external_configuration_does_not_make_project_tests_independent(repo, tmp_path):
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    configure(repo, checks=[["pytest", "-c", str(config)]])
    _, manifest = paired.prepare_pair(repo, "Task")
    check = manifest["profile"]["frozen_checks"][0]
    assert check["file_hashes"]
    assert check["independence"] == "project_checks"
    configure(repo, independent_checks=[["pytest", "-c", str(config)]], replace=True)
    with pytest.raises(ValueError, match="external grader source file"):
        paired.prepare_pair(repo, "Task")


def test_configuration_symmetry_no_baseline_router(repo):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task", router_model="qwen3-0.6b")
    baseline = paired._prepare_config("baseline", run, manifest, phase="task")
    enabled = paired._prepare_config("rippletide", run, manifest, phase="task")
    assert baseline["mcp_servers"] == enabled["mcp_servers"] == {}
    assert baseline["agents"] == enabled["agents"]
    assert baseline["plugins"]["rippletide@personal"]["enabled"] is False
    assert enabled["plugins"]["rippletide@personal"]["enabled"] is True
    assert "hooks" in baseline and "hooks" not in enabled
    assert not (Path(manifest["arms"]["baseline"]["workspace"]) / ".rippletide/config.json").exists()
    environment = paired._environment(manifest["profile"], run / "rippletide", manifest["arms"]["rippletide"], "qwen3-0.6b", "task", "rippletide")
    assert environment["RIPPLETIDE_MODEL"] == "qwen3-0.6b"
    assert environment["RIPPLETIDE_HOOK_MODE"] == "enforce"


def test_project_configs_restored_and_generated_config_preserved(repo):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task")
    workspace = Path(manifest["arms"]["rippletide"]["workspace"])
    (workspace / ".codex").mkdir()
    original = workspace / ".codex/config.toml"
    original.write_text("original=true\n")
    backup = paired._suspend_project_configuration(workspace, run / "rippletide")
    assert not original.exists()
    paired._prepare_config("rippletide", run, manifest, phase="task")
    paired._restore_project_configuration(backup, run / "rippletide")
    assert original.read_text() == "original=true\n"
    assert not (workspace / ".rippletide/config.json").exists()
    assert (run / "rippletide/final-generated-configuration/.rippletide/config.json").is_file()


@pytest.mark.parametrize("folder", [".codex", ".rippletide"])
def test_escaping_configuration_symlinks_never_touch_external_files(repo, tmp_path, folder):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task")
    workspace = Path(manifest["arms"]["rippletide"]["workspace"])
    outside = tmp_path / "untouched"
    outside.mkdir()
    (outside / "config.toml").write_text("sentinel=true\n")
    (outside / "config.json").write_text('{"sentinel":true}\n')
    try:
        (workspace / folder).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink privilege")
        raise
    with pytest.raises(ValueError, match="escapes"):
        paired._suspend_project_configuration(workspace, run / "rippletide")
    if folder == ".rippletide":
        with pytest.raises(ValueError, match="escapes"):
            paired._prepare_config("rippletide", run, manifest, phase="task")
    assert (outside / "config.toml").read_text() == "sentinel=true\n"
    assert (outside / "config.json").read_text() == '{"sentinel":true}\n'


def test_clean_environment_never_implicitly_copies_provider_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")
    monkeypatch.setenv("TRACKER_TOKEN", "authorized")
    environment = clean_environment(names=["TRACKER_TOKEN"])
    assert "DATABASE_PASSWORD" not in environment
    assert environment["TRACKER_TOKEN"] == "authorized"
    assert "CODEX_HOME" not in environment


def test_temporary_auth_reference_and_exact_cleanup(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    source, private = tmp_path / "source-home", tmp_path / "private-home"
    source.mkdir()
    private.mkdir()
    (source / "auth.json").write_text("do not copy")
    monkeypatch.setenv("CODEX_HOME", str(source))
    link = link_auth(private)
    if os.name == "nt":
        assert link[0].is_file() and not link[0].is_symlink()
        assert link[0].read_bytes() == (source / "auth.json").read_bytes()
    else:
        assert link[0].is_symlink()
    unlink_auth(link)
    assert not (private / "auth.json").exists()
    assert (source / "auth.json").read_text() == "do not copy"


def test_owned_process_timeout_and_cancellation(tmp_path):
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    result = run_process(command, cwd=tmp_path, environment=clean_environment(), output=tmp_path / "timeout", timeout=0.1)
    assert result["status"] == "timed_out"
    assert result["wall_seconds"] < 5
    cancel = threading.Event()
    cancel.set()
    result = run_process(command, cwd=tmp_path, environment=clean_environment(), output=tmp_path / "cancel", timeout=20, cancel=cancel)
    assert result["status"] == "cancelled"
    result = run_process(command, cwd=tmp_path, environment=clean_environment(), output=tmp_path / "guard", timeout=20, stop_check=lambda: "exhausted")
    assert result["status"] == "failed" and result["stop_reason"] == "exhausted"


def test_process_prompt_and_nonzero_are_retained(tmp_path):
    result = run_process([sys.executable, "-c", "import sys; print(sys.stdin.read()); sys.exit(3)"],
                         cwd=tmp_path, environment=clean_environment(), output=tmp_path / "task", prompt="task", timeout=5)
    assert result["status"] == "failed" and result["exit_code"] == 3
    assert Path(result["stdout"]).read_text().strip() == "task"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="Owned Unix process-group regression")
def test_one_cleanup_call_kills_child_that_ignores_term(tmp_path):
    # A single cleanup (the KeyboardInterrupt path) must kill a child even if
    # TERM already caused its parent to exit. Keep this proof entirely owned.
    code = ("import os,signal,time\n"
            "child=os.fork()\n"
            "if child == 0:\n"
            " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            " print(os.getpid(),flush=True)\n"
            " while True: time.sleep(1)\n"
            "else:\n"
            " time.sleep(30)\n")
    process = subprocess.Popen([sys.executable, "-c", code], cwd=tmp_path, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    child = int(process.stdout.readline())
    try:
        terminate_owned(process)
        assert process.poll() is not None
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.02)
        assert not state or state.startswith("Z"), "TERM-ignoring child survived its owned process-group cleanup"
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def test_captures_parent_and_recursive_children(tmp_path):
    home, destination = tmp_path / "home", tmp_path / "evidence"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    destination.mkdir()
    session = destination / "session.jsonl"
    session.write_text(json.dumps({"type": "thread.started", "thread_id": "parent"}) + "\n")
    for identity, children in (("parent", ["child"]), ("child", ["grandchild"]), ("grandchild", [])):
        events = [{"payload": {"type": "function_call_output", "output": json.dumps({"agent_id": child})}} for child in children]
        (sessions / f"rollout-{identity}.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")
    result = collect_rollouts(home, session, destination)
    assert Path(result["parent_rollout"]).is_file()
    assert len(result["child_rollouts"]) == 2


def test_captures_v155_child_using_own_id_not_inherited_session_id(tmp_path):
    sessions, destination = tmp_path / "home/sessions", tmp_path / "evidence"
    sessions.mkdir(parents=True)
    destination.mkdir()
    session = destination / "session.jsonl"
    session.write_text(json.dumps({"type": "thread.started", "thread_id": "parent"}) + "\n")
    for identity, ancestor in (("parent", None), ("child", "parent"), ("grandchild", "child")):
        metadata = {"id": identity, "session_id": "parent"}
        if ancestor:
            metadata["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": ancestor, "agent_path": "/root/probe"}}}
        (sessions / f"rollout-{identity}.jsonl").write_text(json.dumps({"type": "session_meta", "payload": metadata}) + "\n")
    result = collect_rollouts(tmp_path / "home", session, destination)
    assert len(result["child_rollouts"]) == 2
    identities = {json.loads(Path(path).read_text())["payload"]["id"] for path in result["child_rollouts"]}
    assert identities == {"child", "grandchild"}


def test_probe_real_stdio_mcp_tool_schema():
    server = {"command": sys.executable, "args": ["-m", "rippletide_uat.probe_server"], "enabled_tools": ["ping"]}
    capability = {"id": "mcp.ping", "kind": "mcp", "operations": ["knowledge_lookup"], "description": "readiness", "invocation": {"server": "probe", "tool": "ping"}, "input_schema": {}}
    result = asyncio.run(paired.probe_capabilities({"probe": server}, [capability], clean_environment()))
    assert result["probe"]["status"] == "ready"
    assert capability["available"] and capability["input_schema"]["type"] == "object"
    server["enabled_tools"] = ["missing"]
    with pytest.raises(ExceptionGroup):
        asyncio.run(paired.probe_capabilities({"probe": server}, [capability], clean_environment()))


def test_task_hook_budget_exhaustion_only(tmp_path):
    path = tmp_path / "hooks.jsonl"
    path.write_text(json.dumps({"phase": "preflight", "exhausted": True}) + "\npartial")
    assert paired._exhausted(path) is None
    path.write_text(json.dumps({"phase": "task", "exhausted": True}) + "\n")
    assert paired._exhausted(path) == "routing_correction_budget_exhausted"


def test_only_real_completed_specialists_count_as_ready(tmp_path):
    paths = []
    for role, completed in (("reviewer", True), ("test_specialist", False)):
        path = tmp_path / f"{role}.jsonl"
        events = [{"type": "session_meta", "payload": {"id": role, "agent_role": role}}]
        if completed:
            events.append({"type": "event_msg", "payload": {"type": "task_complete"}})
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
        paths.append(str(path))
    assert paired.completed_specialists(paths) == {"reviewer"}


def test_model_preflight_requires_actual_requested_model_ready(tmp_path):
    hooks = tmp_path / "hooks.jsonl"
    status = {"ready": True, "worker": {"ready": True}, "model_identity": {"model": "qwen25-rlcd"}}
    event = {"event": "tool_completed", "phase": "preflight", "tool_name": "mcp__rippletide__status",
             "tool_input": {"project_root": str(tmp_path)}, "tool_response": {"content": [{"type": "text", "text": json.dumps(status)}]}}
    hooks.write_text(json.dumps(event) + "\n")
    assert paired.model_readiness(hooks, "qwen25-rlcd", tmp_path)["ready"]
    assert not paired.model_readiness(hooks, "qwen3-0.6b", tmp_path)["ready"]
    assert not paired.model_readiness(hooks, "qwen25-rlcd", tmp_path / "different")["ready"]
    event["phase"] = "task"
    hooks.write_text(json.dumps(event) + "\n")
    assert not paired.model_readiness(hooks, "qwen25-rlcd", tmp_path)["ready"]


def test_host_managed_oauth_preflight_preserves_credentials_outside_profile(tmp_path):
    config = {"mcp_servers": {"linear": {"url": "https://mcp.linear.app/mcp", "enabled_tools": ["get_issue"]}},
              "mcp_preflight": {"linear": {"tool": "get_issue", "arguments": {"id": "EXAMPLE-1"}}}}
    result = validate_tool_config(config)
    calls = result["mcp_preflight"]
    path = tmp_path / "hooks.jsonl"
    event = {"event": "tool_completed", "phase": "preflight", "tool_name": "mcp__linear__get_issue", "call_id": "actual-call",
             "tool_input": {"id": "EXAMPLE-1", "includeRelations": False},
             "tool_response": json.dumps({"content": [{"type": "text", "text": "synthetic approved issue"}], "isError": False})}
    path.write_text(json.dumps(event) + "\n")
    ready = paired.host_mcp_readiness(path, calls)["linear"]
    assert ready["status"] == "ready" and ready["call_id"] == "actual-call"
    assert "not tools/list" in ready["schema_source"]
    event["tool_response"] = {"content": [], "isError": True}
    path.write_text(json.dumps(event) + "\n")
    assert paired.host_mcp_readiness(path, calls)["linear"]["status"] == "unavailable"
    config["mcp_preflight"]["linear"]["tool"] = "update_issue"
    with pytest.raises(ValueError, match="allowlisted"):
        validate_tool_config(config)


def test_baseline_skill_contamination_is_explicitly_detected(tmp_path):
    skill = tmp_path / ".agents/skills/route-capabilities/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: route-capabilities\nUse Rippletide.\n")
    assert paired.baseline_contamination(tmp_path) == [".agents/skills/route-capabilities/SKILL.md"]


def test_untracked_new_code_archived_but_symlink_not_followed(repo, tmp_path):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task")
    workspace = Path(manifest["arms"]["baseline"]["workspace"])
    (workspace / "new.py").write_text("answer = 42\n")
    sensitive = tmp_path / "sensitive"
    sensitive.write_text("private")
    symlink_available = True
    try:
        (workspace / "external-link").symlink_to(sensitive)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        symlink_available = False
    paired._acceptance("baseline", run, manifest, 5, threading.Event())
    result = {entry["path"]: entry for entry in manifest["arms"]["baseline"]["untracked_files"]}
    assert result["new.py"]["status"] == "archived"
    assert Path(result["new.py"]["artifact"]).read_text() == "answer = 42\n"
    if symlink_available:
        assert result["external-link"]["status"] == "not_copied"
    assert manifest["arms"]["baseline"]["acceptance_status"] == "ungraded"


def test_cli_fixture_compatibility_and_new_modes():
    assert parser().parse_args(["prepare", "--scenario", "U02", "--variant", "D"]).variant == "D"
    args = parser().parse_args(["run", "--repo", "/example", "--task", "fix it"])
    assert args.router_model == "qwen25-rlcd" and args.mode == "parallel" and args.repeat == 1
    args = parser().parse_args(["configure", "--repo", "/example", "--check-argv", '["pytest"]'])
    assert args.check_argv == ['["pytest"]']


def test_failed_preflight_retained_without_task_execution(repo, monkeypatch):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task")
    monkeypatch.setattr(paired, "verify_codex", lambda path: "codex-cli 0.155.0")
    monkeypatch.setattr(paired, "link_auth", lambda home: None)
    monkeypatch.setattr(paired, "_preflight", lambda *args: (_ for _ in ()).throw(ValueError("No hooks")))
    import rippletide_uat.paired_evidence as evidence
    monkeypatch.setattr(evidence, "report_pair", lambda path: read_json(path / "pair.json"))
    result = paired.execute_pair(run, manifest, judge=False)
    assert result["status"] == "setup-blocked"
    assert all(arm["session_path"] is None for arm in result["arms"].values())
    assert all(Path(arm["workspace"]).is_dir() for arm in result["arms"].values())


def test_one_auth_cleanup_failure_does_not_skip_other_cleanup(repo, monkeypatch):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task")
    monkeypatch.setattr(paired, "verify_codex", lambda path: "codex-cli 0.155.0")
    monkeypatch.setattr(paired, "link_auth", lambda home: home.parent.name)
    monkeypatch.setattr(paired, "_preflight", lambda *args: None)
    monkeypatch.setattr(paired, "_run_task", lambda *args: None)
    monkeypatch.setattr(paired, "_acceptance", lambda *args: None)
    calls = []
    def cleanup(link):
        calls.append(link)
        if link == "baseline":
            raise RuntimeError("altered link retained")
    monkeypatch.setattr(paired, "unlink_auth", cleanup)
    import rippletide_uat.paired_evidence as evidence
    monkeypatch.setattr(evidence, "report_pair", lambda path: read_json(path / "pair.json"))
    result = paired.execute_pair(run, manifest, judge=False)
    assert calls == ["baseline", "rippletide"]
    assert result["status"] == "failed"
    assert result["cleanup_errors"]["baseline_authentication"] == "altered link retained"
    assert not (Path(manifest["arms"]["rippletide"]["workspace"]) / ".rippletide/config.json").exists()


def test_cli_reports_failed_acceptance_with_nonzero_exit(monkeypatch, capsys):
    import rippletide_uat.cli as cli
    monkeypatch.setattr(sys, "argv", ["rippletide-uat", "run", "--repo", "/example", "--task", "Task"])
    summary = {"runs": [{"status": "completed", "acceptance_status": {"baseline": "passed", "rippletide": "failed"}}]}
    monkeypatch.setattr(paired, "run_pairs", lambda *args, **kwargs: summary)
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code == 1
    assert json.loads(capsys.readouterr().out)["runs"][0]["acceptance_status"]["rippletide"] == "failed"


def test_judge_auth_cleanup_error_still_preserves_report(repo, monkeypatch):
    configure(repo)
    run, manifest = paired.prepare_pair(repo, "Task")
    monkeypatch.setattr(paired, "verify_codex", lambda path: "codex-cli 0.155.0")
    monkeypatch.setattr(paired, "link_auth", lambda home: home.name)
    monkeypatch.setattr(paired, "_preflight", lambda *args: None)
    def task(name, run, manifest, *args):
        manifest["arms"][name].update(status="completed", session_path="recorded.jsonl")
    monkeypatch.setattr(paired, "_run_task", task)
    monkeypatch.setattr(paired, "_acceptance", lambda *args: None)
    def cleanup(link):
        if link == "judge-home":
            raise RuntimeError("altered judge link retained")
    monkeypatch.setattr(paired, "unlink_auth", cleanup)
    import rippletide_uat.paired_evidence as evidence
    import rippletide_uat.correctness as correctness
    monkeypatch.setattr(evidence, "report_pair", lambda path: read_json(path / "pair.json"))
    monkeypatch.setattr(correctness, "grade_pair", lambda *args, **kwargs: {})
    result = paired.execute_pair(run, manifest)
    assert result["cleanup_errors"]["judge_authentication"] == "altered judge link retained"
    assert result["status"] == "failed"
