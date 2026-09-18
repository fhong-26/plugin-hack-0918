"""Small process/configuration boundary for an isolated, pinned Codex host."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable

from .storage import read_events, timestamp


CODEX_VERSION = "codex-cli 0.155.0"


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def pinned_codex() -> Path:
    if os.name == "nt":
        return project_root() / "tools/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
    return project_root() / "tools/codex/node_modules/.bin/codex"


def verify_codex(codex: Path) -> str:
    if not codex.is_file():
        raise FileNotFoundError("Pinned Codex is missing; run npm ci --prefix tools/codex")
    version = subprocess.check_output([str(codex), "--version"], text=True, timeout=30).strip()
    if version != CODEX_VERSION:
        raise ValueError(f"Expected {CODEX_VERSION}; observed {version}")
    help_text = subprocess.check_output([str(codex), "exec", "--help"], text=True, timeout=30)
    if "--dangerously-bypass-hook-trust" not in help_text:
        raise ValueError("Pinned host lacks the verified-hook automation flag")
    return version


def clean_environment(*, names: list[str] = ()) -> dict[str, str]:
    allowed = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT", "CODEX_API_KEY", "UV_CACHE_DIR", *names}
    return {key: value for key, value in os.environ.items() if key in allowed}


def toml_value(value) -> str:
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
    raise TypeError(f"Unsupported configuration value: {type(value).__name__}")


def write_config(home: Path, config: dict) -> Path:
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "config.toml"
    path.write_text("\n".join(f"{key}={toml_value(value)}" for key, value in config.items()) + "\n")
    path.chmod(0o600)
    return path


_AUTH_COPIES = {}


def link_auth(home: Path) -> tuple[Path, Path] | None:
    if os.environ.get("CODEX_API_KEY"):
        return None
    source = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    if not source.is_file():
        return None
    target = home / "auth.json"
    if os.name == "nt":
        import hashlib
        if target.exists():
            raise RuntimeError("Refusing to replace an existing authentication file")
        shutil.copyfile(source, target)
        _AUTH_COPIES[str(target)] = hashlib.sha256(target.read_bytes()).hexdigest()
    else:
        target.symlink_to(source.resolve())
    return target, source.resolve()


def unlink_auth(link: tuple[Path, Path] | None) -> None:
    if link is None:
        return
    target, expected = link
    if os.name == "nt" and str(target) in _AUTH_COPIES:
        import hashlib
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != _AUTH_COPIES[str(target)]:
            raise RuntimeError("Temporary authentication copy changed; refusing to remove it")
        target.unlink()
        _AUTH_COPIES.pop(str(target))
        return
    if not target.is_symlink() or target.readlink() != expected:
        raise RuntimeError("Temporary authentication link changed; refusing to delete a different file")
    target.unlink()


def authenticated(codex: Path, home: Path, environment: dict) -> bool:
    return subprocess.run([str(codex), "login", "status"], cwd=home, env=environment,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30).returncode == 0


def terminate_owned(process: subprocess.Popen) -> None:
    if os.name == "nt":
        import psutil
        if process.poll() is None:
            try:
                descendants = psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            for child in reversed(descendants):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            process.kill()
            process.wait(timeout=3)
            _, alive = psutil.wait_procs(descendants, timeout=1)
            if alive:
                raise RuntimeError("An owned child survived Windows process cleanup")
        return
    exited = process.poll() is not None
    deadline = time.monotonic() + (0.25 if exited else 5)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if not exited:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    # The parent exiting on TERM does not prove its children exited. Always
    # inspect the owned group, including KeyboardInterrupt's single cleanup call.
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait()


def run_process(argv: list[str], *, cwd: Path, environment: dict, output: Path, timeout: float,
                prompt: str | None = None, cancel: threading.Event | None = None,
                stop_check: Callable[[], str | None] | None = None) -> dict:
    """Own only this process group; keep timeout/cancellation evidence intact."""
    stdout_path, stderr_path = output.with_suffix(".jsonl"), output.with_suffix(".stderr.log")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    started_at, started = timestamp(), time.monotonic()
    status, stop_reason = "completed", None
    with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
        process = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, text=True, encoding="utf-8", start_new_session=True)
        try:
            # Prompts are bounded by the runner. communicate handles a closed
            # stdin and polling without losing subprocess ownership on failure.
            pending_input = prompt
            while True:
                if stop_check and (stop_reason := stop_check()):
                    status = "failed"
                    terminate_owned(process)
                    break
                if cancel is not None and cancel.is_set():
                    status = "cancelled"
                    terminate_owned(process)
                    break
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    status = "timed_out"
                    terminate_owned(process)
                    break
                try:
                    process.communicate(pending_input, timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
            if status == "completed" and process.returncode:
                status = "failed"
        finally:
            terminate_owned(process)
    return {"argv": argv, "status": status, "exit_code": process.returncode,
            "started_at": started_at, "finished_at": timestamp(),
            "wall_seconds": round(time.monotonic() - started, 6),
            "stdout": str(stdout_path), "stderr": str(stderr_path), "stop_reason": stop_reason}


def collect_rollouts(home: Path, session_path: Path, destination: Path) -> dict:
    events = read_events(session_path)
    parent = next((event.get("thread_id") for event in events if event.get("type") == "thread.started"), None)
    result = {"thread_id": parent, "parent_rollout": None, "child_rollouts": []}
    if not parent:
        return result
    sources = list((home / "sessions").rglob("*.jsonl"))
    linked_children: dict[str, list[str]] = {}
    by_identity: dict[str, list[Path]] = {}
    for source in sources:
        for event in read_events(source):
            if event.get("type") != "session_meta":
                continue
            metadata = event.get("payload", {})
            # CLI 0.155 children carry their parent's session_id; payload.id
            # is the child's own identity. Never merge their token counters.
            identity = metadata.get("id")
            spawn = metadata.get("source", {})
            spawn = spawn.get("subagent", {}).get("thread_spawn", {}) if isinstance(spawn, dict) else {}
            ancestor = metadata.get("parent_thread_id") or spawn.get("parent_thread_id")
            if identity:
                by_identity.setdefault(identity, []).append(source)
                if ancestor:
                    linked_children.setdefault(ancestor, []).append(identity)
            break
    pending, visited = [parent], set()
    while pending:
        thread_id = pending.pop(0)
        if thread_id in visited or not re.fullmatch(r"[A-Za-z0-9_-]+", thread_id):
            continue
        visited.add(thread_id)
        matches = by_identity.get(thread_id, [source for source in sources if source.name.endswith(f"-{thread_id}.jsonl")])
        if len(matches) != 1:
            continue
        target = destination / ("parent.raw.jsonl" if thread_id == parent else f"child-{thread_id}.raw.jsonl")
        shutil.copyfile(matches[0], target)
        if thread_id == parent:
            result["parent_rollout"] = str(target)
        else:
            result["child_rollouts"].append(str(target))
        pending.extend(linked_children.get(thread_id, []))
        for event in read_events(target):
            payload = event.get("payload", {})
            if payload.get("type") != "function_call_output":
                continue
            try:
                value = json.loads(payload.get("output", ""))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict) and isinstance(value.get("agent_id"), str):
                pending.append(value["agent_id"])
    return result


def capture_session(codex: Path, *, home: Path, workspace: Path, run: Path, environment: dict,
                    prompt: str, timeout: float, cancel: threading.Event | None = None,
                    stop_check: Callable[[], str | None] | None = None) -> dict:
    # Only vetted generated hooks in the private configuration are trusted.
    # This is not a sandbox or approval bypass.
    command = [str(codex), "exec", "--json", "--sandbox", "workspace-write",
               "--dangerously-bypass-hook-trust", "--ignore-rules", "-c", 'approval_policy="never"', "-"]
    result = run_process(command, cwd=workspace, environment=environment, output=run / "session",
                         prompt=prompt, timeout=timeout, cancel=cancel, stop_check=stop_check)
    result["session_path"] = result["stdout"]
    result.update(collect_rollouts(home, Path(result["stdout"]), run))
    observed = []
    if result["parent_rollout"]:
        for event in read_events(Path(result["parent_rollout"])):
            if event.get("type") != "turn_context":
                continue
            context = event.get("payload", {})
            mode = context.get("collaboration_mode", {}).get("settings", {})
            settings = {"model": context.get("model"), "effort": mode.get("reasoning_effort"),
                        "source": "host turn_context", "effort_explicit": mode.get("reasoning_effort") is not None}
            if settings not in observed:
                observed.append(settings)
    result["observed_settings"] = observed
    return result
