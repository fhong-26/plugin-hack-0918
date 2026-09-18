"""Isolated Codex routing reference; explicitly distinct from task execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from rippletide.personalization import atomic_json, digest, read_json
from rippletide_uat.paired_host import (pinned_codex, verify_codex, clean_environment,
    link_auth, unlink_auth, write_config, run_process, collect_rollouts)
from .dataset import read_rows, training_history
from .runner import with_memory
from .evaluation import grade, summary


def run_reference(dataset: Path, output: Path, *, model: str, effort: str = "high", limit: int | None = None,
                  train_limit: int = 12) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    executable = pinned_codex()
    version = verify_codex(executable)
    rows = read_rows(dataset, "test")
    if limit:
        rows = rows[:limit]
    train = read_rows(dataset, "train")
    history = {}
    import random
    for user in sorted({r["user_id"] for r in rows}):
        subset = [r for r in train if r["user_id"] == user and r["kind"] != "rule"]
        random.Random(31).shuffle(subset)
        history[user] = training_history(subset[:train_limit], user)
    manifest = {"version": 1, "level": "constrained Codex routing reference, no target-tool execution",
                "codex_version": version, "model": model, "effort": effort,
                "dataset_digest": read_json(dataset / "manifest.json")["dataset_digest"],
                "test_ids": [r["id"] for r in rows], "same_history_as_memory_control": True,
                "train_limit_per_user": train_limit}
    if (output / "manifest.json").exists() and read_json(output / "manifest.json") != manifest:
        raise ValueError("Existing reference run has different settings")
    atomic_json(output / "manifest.json", manifest)
    grades, usage = [], []
    for index, row in enumerate(rows):
        case = output / row["id"]
        if (case / "result.json").exists():
            record = read_json(case / "result.json")
            grades.append(record["grade"])
            usage.append(record["usage"])
            continue
        case.mkdir(parents=True, exist_ok=True)
        home, workspace = case / "codex-home", case / "workspace"
        home.mkdir(exist_ok=True)
        workspace.mkdir(exist_ok=True)
        config = {"model": model, "model_reasoning_effort": effort, "approval_policy": "never",
                  "sandbox_mode": "read-only", "web_search": "disabled",
                  "projects": {str(workspace.resolve()): {"trust_level": "trusted"}}}
        write_config(home, config)
        choices = [c["id"] for c in row["packet"]["candidates"]] + ["defer"]
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "route_id": {"type": "string", "enum": choices}}, "required": ["route_id"]}
        atomic_json(case / "schema.json", schema)
        prompt = ("This is a bounded tool-selection evaluation. Select the registered capability that should be called next. "
                  "Do not perform the task, invoke tools, inspect files, browse, or delegate. "
                  "Use the current need and user preferences; choose defer only if the need is unclear or no candidate fits. "
                  "Return only the required JSON.\n" + json.dumps(with_memory(row, history[row["user_id"]]), ensure_ascii=False))
        (case / "prompt.txt").write_text(prompt, encoding="utf-8")
        env = clean_environment()
        env["CODEX_HOME"] = str(home.resolve())
        env["PYTHONUTF8"] = "1"
        auth = link_auth(home)
        started = time.perf_counter()
        try:
            result = run_process([str(executable), "exec", "--json", "--skip-git-repo-check",
                "--sandbox", "read-only", "--ignore-rules", "--output-schema", str((case / "schema.json").resolve()),
                "--output-last-message", str((case / "answer.json").resolve()), "-"],
                cwd=workspace, environment=env, output=case / "session", prompt=prompt, timeout=180)
            if result["status"] == "completed" and (case / "answer.json").exists():
                answer = read_json(case / "answer.json")["route_id"]
                if answer not in choices:
                    raise ValueError("Codex returned an unregistered choice")
                prediction = {"status": "defer" if answer == "defer" else "selected", "route_id": answer,
                              "reason_code": "MODEL_DEFER" if answer == "defer" else "MODEL_SELECTION"}
            else:
                prediction = {"status": "defer", "reason_code": "CODEX_REFERENCE_FAILED"}
            prediction["elapsed_ms"] = (time.perf_counter() - started) * 1000
            events = [json.loads(line) for line in Path(result["stdout"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("{")]
            measured_usage = [e["usage"] for e in events if e.get("type") == "turn.completed" and e.get("usage")]
            observed = collect_rollouts(home, Path(result["stdout"]), case)
            record = {"grade": grade(row, prediction), "usage": measured_usage, "process": result,
                      "evidence": observed, "prompt_digest": digest(prompt), "actual_tool_execution": False}
            atomic_json(case / "result.json", record)
            grades.append(record["grade"])
            usage.append(measured_usage)
        finally:
            unlink_auth(auth)
        print(json.dumps({"phase": "codex_reference", "done": index + 1, "total": len(rows),
                          "matched": grades[-1]["preference_match"]}), flush=True)
        atomic_json(output / "progress-results.json", {"manifest": manifest, "summary": summary(grades), "grades": grades})
        if prediction["reason_code"] == "CODEX_REFERENCE_FAILED":
            # Keep the failed attempt; do not spend a whole cohort on a broken host.
            break
    final = {"manifest": manifest, "summary": summary(grades), "grades": grades, "usage": usage,
             "complete": len(grades) == len(rows), "executed_tools": False}
    atomic_json(output / "results.json", final)
    return final
