from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .storage import read_json, timestamp, write_json


def grade_sessions(workspace: Path) -> dict:
    process = subprocess.run([sys.executable, "-m", "rippletide_uat.grade_worker", "--workspace", str(workspace)], capture_output=True, text=True, timeout=30)
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        return {"status": "failed", "checks": [], "error": process.stderr or process.stdout, "exit_code": process.returncode}
    result["exit_code"] = process.returncode
    return result


def grade_taskboard(workspace: Path, run: Path, stage: str) -> dict:
    if not (workspace / "app.py").is_file():
        return {"status": "failed", "checks": [{"name": "entrypoint", "passed": False, "error": "app.py does not exist"}]}
    artifact_dir = run / "grader-artifacts" / uuid.uuid4().hex
    artifact_dir.mkdir(parents=True)
    database = artifact_dir / "tasks.sqlite3"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    process = None
    checks = []

    def request(method: str, path: str, body=None):
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base_url + path, data=payload, method=method, headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read().decode()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            return response.status, value

    def check(name: str, condition: bool, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(name)

    def start():
        nonlocal process
        with (artifact_dir / "server.log").open("a") as logfile:
            process = subprocess.Popen([sys.executable, "app.py", "--port", str(port), "--database", str(database)], cwd=workspace, stdout=logfile, stderr=logfile)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Application exited at startup: {process.returncode}")
            try:
                if request("GET", "/health")[0] == 200:
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        raise TimeoutError("Application did not become healthy within 10 seconds")

    def stop():
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    try:
        start()
        status, page = request("GET", "/")
        check("html_interface", status == 200 and isinstance(page, str) and "<" in page)
        status, first = request("POST", "/api/tasks", {"title": "Write regression tests"})
        check("create_task", status == 201 and isinstance(first, dict) and "id" in first and first.get("title") == "Write regression tests" and first.get("completed") is False, first)
        status, second = request("POST", "/api/tasks", {"title": "Review the change"})
        check("second_task", status == 201 and second.get("id") != first["id"])
        check("empty_title_rejected", request("POST", "/api/tasks", {"title": "   "})[0] == 400)
        status, listed = request("GET", "/api/tasks")
        check("list_creation_order", status == 200 and isinstance(listed, list) and [item["id"] for item in listed] == [first["id"], second["id"]])
        status, completed = request("PATCH", f"/api/tasks/{first['id']}", {"completed": True})
        check("complete_task", status == 200 and completed.get("completed") is True)
        check("unknown_task", request("PATCH", "/api/tasks/999999999", {"completed": True})[0] == 404)
        if stage == "filter":
            status, completed_only = request("GET", "/api/tasks?completed=true")
            check("completed_filter", status == 200 and [item["id"] for item in completed_only] == [first["id"]])
            status, active_only = request("GET", "/api/tasks?completed=false")
            check("active_filter", status == 200 and [item["id"] for item in active_only] == [second["id"]])
            check("invalid_filter", request("GET", "/api/tasks?completed=maybe")[0] == 400)
            check("filter_preserves_tasks", len(request("GET", "/api/tasks")[1]) == 2)
        stop()
        start()
        status, persisted = request("GET", "/api/tasks")
        check("persistent_after_restart", status == 200 and len(persisted) == 2 and persisted[0]["completed"] is True)
    except Exception as exc:
        if not checks or checks[-1]["passed"]:
            checks.append({"name": "application_execution", "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        stop()
    return {"status": "passed" if checks and all(item["passed"] for item in checks) else "failed", "checks": checks, "artifacts": str(artifact_dir), "stage": stage}


def check_run(run: Path, stage: str = "filter") -> dict:
    manifest = read_json(run / "run.json")
    grader = manifest["scenario_definition"]["grader"]
    workspace = Path(manifest["workspace"])
    if grader == "sessions":
        result = grade_sessions(workspace)
    elif grader == "taskboard":
        result = grade_taskboard(workspace, run, stage)
    else:
        result = {"status": "unknown", "checks": [], "reason": "This scenario requires real session evidence and reviewed observations; application tests alone cannot grade it."}
    result.update({"run_id": manifest["run_id"], "checked_at": timestamp(), "grader": grader})
    write_json(run / f"acceptance-{stage if grader == 'taskboard' else 'results'}.json", result)
    return result
