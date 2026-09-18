#!/usr/bin/env python3
"""Persistent JSONL adapter for the plugin's full-context select_tool API."""

import argparse
import contextlib
import json
from pathlib import Path
import sys
import time

# Direct script execution must not shadow the installed rippletide package.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]


def choose(worker, task: dict) -> dict:
    """Preserve the complete input and time the same selector used by the plugin."""
    started = None
    try:
        from rippletide.selection import select_tool
        request = {
            "context": json.dumps({key: task[key] for key in
                                   ("instruction", "context", "host_instructions")},
                                  ensure_ascii=False, separators=(",", ":")),
            "question": "What is the best tool for the next step?",
            "tools": [{"name": tool["id"], "description": tool["description"]}
                      for tool in task["tools"]],
        }
        started = time.perf_counter()
        response = select_tool(worker, **request)
        elapsed = time.perf_counter() - started
        selected = response.get("tool") if response.get("status") == "selected" else None
        return {
            "tool_id": selected, "elapsed_s": elapsed, "cost_usd": 0,
            "error": None if selected else response.get("reason_code", "SELECTION_ERROR"),
            "metadata": {"selector_response": response},
        }
    except Exception as exc:
        return {"tool_id": None, "elapsed_s": time.perf_counter() - started if started is not None else None,
                "cost_usd": 0, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen25-rlcd", help="Installed repository model alias")
    args = parser.parse_args()
    protocol = sys.stdout

    def send(value):
        protocol.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        protocol.flush()

    started = time.perf_counter()
    worker = None
    # Keep plugin/library chatter off the JSONL channel, including warmup.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            from rippletide.artifacts import read_artifacts
            from rippletide.identity import data_directory, model_identity
            from rippletide.labels import context_limit
            from rippletide.model import WorkerManager
            from rippletide.selection import SELECTION_TIMEOUT_SECONDS

            data_dir = data_directory()
            worker = WorkerManager(data_dir, model=args.model)
            if not worker.start(wait=True):
                raise RuntimeError(worker.status().get("error") or "Model worker did not become ready")
            artifacts = read_artifacts(data_dir, model=args.model)
            metadata = {
                "adapter": "repository-rippletide-select-tool", "model_identity": model_identity(args.model),
                "startup_elapsed_s": time.perf_counter() - started,
                "worker_startup_ms": worker.status().get("startup_ms"),
                "scope": "Public select_tool API; no MCP transport, hooks, tool execution, or Codex fallback",
                "candidate_order": "Supplied order preserved; no preferences or registry filtering",
                "input_token_limit": context_limit(artifacts["weights_path"]),
                "route_timeout_s": SELECTION_TIMEOUT_SECONDS,
                "cost_scope": "No API charge; local hardware and energy costs excluded",
            }
            send({"ready": True, "metadata": metadata})
        except Exception as exc:
            send({"ready": False, "error": f"{type(exc).__name__}: {exc}",
                  "metadata": {"startup_elapsed_s": time.perf_counter() - started}})
            if worker is not None:
                worker.close()
            return 1
        try:
            for line in sys.stdin:
                try:
                    result = choose(worker, json.loads(line))
                except Exception as exc:
                    result = {"tool_id": None, "elapsed_s": None, "cost_usd": 0,
                              "error": f"{type(exc).__name__}: {exc}"}
                send(result)
        finally:
            worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
