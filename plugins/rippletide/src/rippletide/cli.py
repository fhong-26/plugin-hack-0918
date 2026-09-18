"""User-facing CLI. stdout contains the command result; diagnostics use stderr."""

import argparse
import json
import sys

from rippletide.artifacts import setup_artifacts
from rippletide.config import load_config, update_preferences
from rippletide.router import Router


def main():
    parser = argparse.ArgumentParser(prog="rippletide")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="Download, verify, and load the exact pinned engine and weights")
    setup.add_argument("--skip-warmup", action="store_true", help="Download only; readiness remains unverified")
    sub.add_parser("serve", help="Run the persistent MCP server over standard input/output")
    for name in ("status", "route", "report", "preferences"):
        command = sub.add_parser(name)
        command.add_argument("--project-root", required=True)
        if name == "route":
            command.add_argument("--request", required=True, help="A JSON routing request; project_root comes from --project-root")
        elif name == "report":
            command.add_argument("--limit", type=int, default=20)
        elif name == "preferences":
            command.add_argument("--set", dest="update", required=True, help="Explicit JSON preference patch")
        elif name == "status":
            command.add_argument("--no-load", action="store_true", help="Inspect artifacts and configuration without loading the worker")
    args = parser.parse_args()
    if args.command == "serve":
        from rippletide.server import serve
        serve()
        return
    router = Router()
    exit_code = 0
    try:
        if args.command == "setup":
            artifacts = setup_artifacts(router.data_dir)
            ready = False if args.skip_warmup else router.worker.start(wait=True)
            result = {"installed": True, "ready": ready, "artifacts": artifacts, "worker": router.worker.status()}
            if not ready and not args.skip_warmup:
                exit_code = 1
        elif args.command == "preferences":
            result = update_preferences(args.project_root, json.loads(args.update))
        elif args.command == "report":
            result = router.report(args.project_root, args.limit)
        else:
            config, _, _ = load_config(args.project_root)
            # Cold startup is explicitly outside the measured two-second route call.
            if config.variant == "D" and not getattr(args, "no_load", False):
                router.worker.start(wait=True)
            if args.command == "status":
                result = router.status(args.project_root)
            else:
                request = json.loads(args.request)
                if not isinstance(request, dict):
                    raise ValueError("--request must be a JSON object")
                request["project_root"] = args.project_root
                result = router.route(**request)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        exit_code = 1
    finally:
        router.close()
    if exit_code:
        raise SystemExit(exit_code)
