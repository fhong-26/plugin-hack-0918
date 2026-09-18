#!/usr/bin/env python3
"""Persistent JSONL adapter for this repository's unmodified Router.route API."""

import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

# Direct script execution must not shadow the installed rippletide package.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]


def choose(router, root: Path, task: dict) -> dict:
    """Prepare registration first, then time exactly the public routing call."""
    started = None
    try:
        capabilities = [{
            "id": tool["id"],
            "kind": "mcp" if tool["id"].startswith(("mcp__", "mcp.")) else "native",
            "operations": ["benchmark_tool_selection"],
            "description": tool["description"], "available": True,
            "invocation": {"tool": tool["id"]}, "input_schema": {"type": "object"},
        } for tool in task["tools"]]
        config_dir = root / ".rippletide"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.json").write_text(json.dumps({
            "version": 1, "variant": "D", "registry_version": "benchmark-v1", "fixture_mode": True,
            "preferences": {}, "capabilities": capabilities,
        }, ensure_ascii=False), encoding="utf-8")
        request = {
            "project_root": str(root), "operation": "benchmark_tool_selection",
            "goal": task["instruction"],
            "facts": {key: task[key] for key in ("context", "host_instructions")},
        }
        started = time.perf_counter()
        response = router.route(**request)
        elapsed = time.perf_counter() - started
        selected = response.get("route_id") if response.get("status") == "selected" else None
        return {
            "tool_id": selected, "elapsed_s": elapsed, "cost_usd": 0,
            "error": None if selected else response.get("reason_code", "ROUTER_DEFER"),
            "metadata": {"router_response": response},
        }
    except Exception as exc:
        return {"tool_id": None, "elapsed_s": time.perf_counter() - started if started else 0,
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
    router = None
    with tempfile.TemporaryDirectory(prefix="rippletide-benchmark-") as temporary, contextlib.ExitStack() as stack:
        # Keep plugin/library chatter off the JSONL channel, including warmup.
        stack.enter_context(contextlib.redirect_stdout(sys.stderr))
        try:
            from rippletide.identity import INPUT_TOKEN_LIMIT, ROUTE_TIMEOUT_SECONDS, model_identity
            from rippletide.router import Router

            root = Path(temporary)
            # The temporary registry's fixture_mode uses the plugin's existing
            # preference isolation; no user config or authentication is changed.
            stack.enter_context(patch.dict(os.environ, {"RIPPLETIDE_RUN_DIR": str(root / ".rippletide")}))
            router = Router(model=args.model)
            if not router.worker.start(wait=True):
                raise RuntimeError(router.worker.status().get("error") or "Model worker did not become ready")
            metadata = {
                "adapter": "repository-rippletide", "model_identity": model_identity(router.model),
                "startup_elapsed_s": time.perf_counter() - started,
                "worker_startup_ms": router.worker.status().get("startup_ms"),
                "scope": "Public Router.route chooser API; no MCP transport, hooks, tool execution, or Codex fallback",
                "global_preferences": "Temporary registry fixture_mode; no persistent user preference edits",
                "candidate_order": "Input registered unchanged; public Router.route sorts candidates by ID",
                "input_token_limit": INPUT_TOKEN_LIMIT, "route_timeout_s": ROUTE_TIMEOUT_SECONDS,
                "cost_scope": "No API charge; local hardware and energy costs excluded",
            }
            send({"ready": True, "metadata": metadata})
        except Exception as exc:
            send({"ready": False, "error": f"{type(exc).__name__}: {exc}",
                  "metadata": {"startup_elapsed_s": time.perf_counter() - started}})
            if router is not None:
                router.worker.close()
            return 1
        try:
            for line in sys.stdin:
                try:
                    task = json.loads(line)
                    result = choose(router, root, task)
                except Exception as exc:
                    result = {"tool_id": None, "elapsed_s": 0, "cost_usd": 0,
                              "error": f"{type(exc).__name__}: {exc}"}
                send(result)
        finally:
            router.worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
