"""User-facing CLI. stdout contains the command result; diagnostics use stderr."""

import argparse
import json
import sys

from rippletide.artifacts import read_artifacts, setup_artifacts
from rippletide.catalog import DEFAULT_MODEL, MODELS, model_spec
from rippletide.config import load_config, update_preferences
from rippletide.identity import data_directory, model_identity
from rippletide.router import Router


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "learning":
        from rippletide.learning import main as learning_main
        learning_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(prog="rippletide")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="Download, verify, and load the exact pinned engine and weights")
    setup.add_argument("--skip-warmup", action="store_true", help="Download only; readiness remains unverified")
    setup.add_argument("--model", choices=MODELS, help="Model alias; defaults to RIPPLETIDE_MODEL or qwen25-rlcd")
    serving = sub.add_parser("serve", help="Run the persistent MCP server over standard input/output")
    serving.add_argument("--model", choices=MODELS, help="One pinned local model for this server process")
    sub.add_parser("models", help="List local model options and installed artifact readiness without loading")
    for name in ("status", "route", "report", "preferences"):
        command = sub.add_parser(name)
        command.add_argument("--project-root", required=True)
        if name in {"status", "route"}:
            command.add_argument("--model", choices=MODELS)
        if name == "route":
            command.add_argument("--request", required=True, help="A JSON routing request; project_root comes from --project-root")
        elif name == "report":
            command.add_argument("--limit", type=int, default=20)
        elif name == "preferences":
            command.add_argument("--set", dest="update", required=True, help="Explicit JSON preference patch")
        elif name == "status":
            command.add_argument("--no-load", action="store_true", help="Inspect artifacts and configuration without loading the worker")
    args = parser.parse_args()
    try:
        selected_model = model_spec(getattr(args, "model", None)).alias
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "serve":
        from rippletide.server import serve
        serve(model=selected_model)
        return
    if args.command == "models":
        records = []
        for alias in MODELS:
            try:
                read_artifacts(data_directory(), model=alias)
                installed = True
            except (ValueError, OSError, KeyError):
                installed = False
            records.append({**model_identity(alias), "default": alias == DEFAULT_MODEL, "installed": installed})
        print(json.dumps({"default": DEFAULT_MODEL, "selected": selected_model, "models": records}, indent=2))
        return
    router = Router(model=selected_model)
    exit_code = 0
    try:
        if args.command == "setup":
            artifacts = setup_artifacts(router.data_dir, model=router.model)
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
