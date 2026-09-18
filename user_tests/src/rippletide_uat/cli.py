from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from .evidence import compare, correlate, report, session_summary, verify_agents
from .graders import check_run
from .prepare import package_root, prepare, prepare_semantic, probe_server
from .scenarios import expected_evidence
from .storage import append_event, read_json, timestamp, write_json


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Prepare real local tools and projects for Rippletide user acceptance testing")
    commands = root.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Create a fresh run without overwriting anything")
    prepare_parser.add_argument("--scenario", required=True, choices=[f"U{i:02}" for i in range(1, 10)])
    prepare_parser.add_argument("--variant", required=True, choices=list("ABCD"))
    prepare_parser.add_argument("--output-root", type=Path, default=package_root().parent / ".uat-runs")
    prepare_parser.add_argument("--plugin-root", type=Path, default=package_root().parent / "plugins" / "rippletide")
    prepare_parser.add_argument("--run-id")
    prepare_parser.add_argument("--failure", choices=["docs", "tracker", "reviewer", "test_specialist", "model"])
    prepare_parser.add_argument("--comparison-scenario", choices=["U02", "U05"], default="U02")
    serve = commands.add_parser("serve", help="Run a genuine stdio MCP service")
    serve.add_argument("server", choices=["docs", "tracker"])
    serve.add_argument("--run", type=Path, required=True)
    check = commands.add_parser("check", help="Run independent application acceptance checks")
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--stage", choices=["starter", "filter"], default="filter")
    for name in ("report", "verify-agents", "correlate"):
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--session", type=Path, required=name != "report")
        if name == "correlate":
            command.add_argument("--decision-id", required=True)
            command.add_argument("--call-id", required=True)
            command.add_argument("--note", required=True)
    preflight = commands.add_parser("preflight", help="Check the real local servers; no model or agent result is fabricated")
    preflight.add_argument("--run", type=Path, required=True)
    semantic = commands.add_parser("prepare-semantic", help="Use the isolated official Chroma MCP integration")
    semantic.add_argument("--run", type=Path, required=True)
    semantic.add_argument("--integration-root", type=Path, default=package_root().parent / "integrations" / "chroma")
    intervention = commands.add_parser("intervention", help="Record a real observed user interaction")
    intervention.add_argument("--run", type=Path, required=True)
    intervention.add_argument("--category", choices=["required", "setup", "permission", "planned_prompt", "optional_feedback", "inspection"], required=True)
    intervention.add_argument("--description", required=True)
    intervention.add_argument("--decision-id")
    finalize = commands.add_parser("finalize", help="Record reviewed actual outcome and ledger completeness")
    finalize.add_argument("--run", type=Path, required=True)
    finalize.add_argument("--session", type=Path, required=True)
    finalize.add_argument("--outcome", choices=["success", "failed", "stalled", "abandoned"], required=True)
    finalize.add_argument("--ledger-complete", action="store_true")
    annotate = commands.add_parser("record-check", help="Record a reviewed scenario assertion with evidence")
    annotate.add_argument("--run", type=Path, required=True)
    annotate.add_argument("--name", required=True)
    annotate.add_argument("--status", choices=["passed", "failed", "blocked", "unknown"], required=True)
    annotate.add_argument("--evidence", required=True)
    pair = commands.add_parser("compare")
    pair.add_argument("--runs", nargs="+", type=Path, required=True)
    live = commands.add_parser("live-readiness", help="Inspect explicit provider targets and supplied call evidence; never contact or mutate remote services")
    live.add_argument("--linear-project-id")
    live.add_argument("--notion-page-id")
    live.add_argument("--session", type=Path)
    configure = commands.add_parser("configure", help="Save an explicit paired-test project profile outside source control")
    configure.add_argument("--repo", type=Path, required=True)
    configure.add_argument("--bootstrap-argv", action="append", default=[], help='Repeatable JSON argv, e.g. ["uv","sync","--locked"]')
    configure.add_argument("--check-argv", action="append", default=[], help='Repeatable project-check JSON argv; results are provisional, not independent grades')
    configure.add_argument("--independent-check-argv", action="append", default=[], help='Explicitly approved external grader JSON argv, e.g. ["python","/path/grader.py","{workspace}"]')
    configure.add_argument("--tool-config", type=Path, help="Approved MCP/agent/capability JSON; never a personal Codex config")
    configure.add_argument("--model", help="Codex model; independent of the local routing model")
    configure.add_argument("--effort", choices=["minimal", "low", "medium", "high", "xhigh"])
    configure.add_argument("--replace", action="store_true")
    run = commands.add_parser("run", help="Run matched Codex-alone and Rippletide tasks in fresh isolated worktrees")
    run.add_argument("--repo", type=Path, required=True)
    task = run.add_mutually_exclusive_group(required=True)
    task.add_argument("--task")
    task.add_argument("--task-file", type=Path)
    run.add_argument("--base", default="main")
    run.add_argument("--router-model", choices=["qwen25-rlcd", "qwen3-0.6b", "minicpm5-2b", "qwen3.5-4b"], default="qwen25-rlcd")
    run.add_argument("--mode", choices=["parallel", "sequential"], default="parallel")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--output-root", type=Path)
    run.add_argument("--codex", type=Path, help="Must be the pinned Codex 0.155.0; defaults to tools/codex/node_modules/.bin/codex")
    run.add_argument("--timeout", type=float, default=600)
    run.add_argument("--preflight-timeout", type=float, default=180)
    run.add_argument("--check-timeout", type=float, default=180)
    run.add_argument("--no-judge", action="store_true", help="Retain ungraded choices for a later manual audit")
    audit = commands.add_parser("audit-grade", help="Append a human correctness judgment without replacing original evidence")
    audit.add_argument("--run", type=Path, required=True)
    audit.add_argument("--call-id", required=True)
    audit.add_argument("--verdict", choices=["correct", "incorrect", "uncertain", "ungradable"], required=True)
    audit.add_argument("--reason", required=True)
    return root


def main():
    args = parser().parse_args()
    exit_code = 0
    try:
        if args.command == "configure":
            from .profiles import argv_value, configure
            result = configure(args.repo, bootstrap=[argv_value(value) for value in args.bootstrap_argv],
                               checks=[argv_value(value) for value in args.check_argv],
                               independent_checks=[argv_value(value) for value in args.independent_check_argv], tool_config=args.tool_config,
                               model=args.model, effort=args.effort, replace=args.replace)
        elif args.command == "run":
            from .paired import run_pairs
            result = run_pairs(args.repo, args.task if args.task is not None else args.task_file.read_text(),
                               base=args.base, router_model=args.router_model, mode=args.mode, repeat=args.repeat,
                               output_root=args.output_root, codex=args.codex, timeout=args.timeout,
                               preflight_timeout=args.preflight_timeout, check_timeout=args.check_timeout,
                               judge=not args.no_judge)
            exit_code = 0 if all(run["status"] == "completed" and "failed" not in run.get("acceptance_status", {}).values()
                                 for run in result["runs"]) else 1
        elif args.command == "audit-grade":
            from .correctness import audit_grade
            from .paired_evidence import report_pair
            result = audit_grade(args.run.resolve(), args.call_id, args.verdict, args.reason)
            report_pair(args.run.resolve())
        elif args.command == "prepare":
            run = prepare(args.scenario, args.variant, args.output_root, args.plugin_root, run_id=args.run_id, failure=args.failure, comparison_scenario=args.comparison_scenario)
            manifest = read_json(run / "run.json")
            result = {"run": str(run), "workspace": manifest["workspace"], "prompt": manifest["scenario_definition"]["prompt"], "followup": manifest["scenario_definition"].get("followup"), "agent_preflight_prompt": str(run / "agent-preflight-prompt.txt"), "commands": {"check": [sys.executable, "-m", "rippletide_uat", "check", "--run", str(run)], "report": [sys.executable, "-m", "rippletide_uat", "report", "--run", str(run)]}, "note": "Agents are configured but require a fresh named-role invocation before verify-agents can mark them ready. Semantic search requires prepare-semantic. Model readiness belongs to the plugin setup."}
        elif args.command == "serve":
            from .servers import create_server
            create_server(args.server, args.run.resolve()).run()
            return
        elif args.command == "check":
            result = check_run(args.run.resolve(), args.stage)
            exit_code = 0 if result["status"] == "passed" else 1
        elif args.command == "report":
            if (args.run / "pair.json").is_file():
                from .paired_evidence import report_pair
                result = report_pair(args.run.resolve())
            else:
                result = report(args.run.resolve(), args.session)
        elif args.command == "verify-agents":
            result = verify_agents(args.run.resolve(), args.session.resolve())
            exit_code = 0 if result["ready"] else 1
        elif args.command == "correlate":
            result = correlate(args.run.resolve(), args.session.resolve(), args.decision_id, args.call_id, args.note)
        elif args.command == "preflight":
            manifest = read_json(args.run / "run.json")
            result = {"servers": {kind: asyncio.run(probe_server(kind, args.run.resolve())) if f"uat_{kind}" in manifest["servers"] else {"status": "unavailable", "evidence": "Server deliberately disconnected"} for kind in ("docs", "tracker")}, "agents": "Use agent-preflight-prompt.txt in a fresh Codex session, then verify-agents with its actual JSONL.", "model": "Use rippletide status --project-root WORKSPACE; this kit does not substitute a model."}
            exit_code = 0 if all(value["status"] == "ready" for value in result["servers"].values()) else 1
        elif args.command == "prepare-semantic":
            result = prepare_semantic(args.run.resolve(), args.integration_root.resolve())
            exit_code = 0 if result.get("ready") else 1
        elif args.command == "intervention":
            manifest = read_json(args.run / "run.json")
            result = append_event(args.run / "interventions.jsonl", manifest["run_id"], "human_interaction", category=args.category, description=args.description, decision_id=args.decision_id)
        elif args.command == "finalize":
            manifest = read_json(args.run / "run.json")
            if not args.session.is_file() or not session_summary(args.session)["available"]:
                raise ValueError("A real session JSONL file is required")
            manifest.update(task_outcome=args.outcome, session=str(args.session.resolve()), intervention_ledger_complete=args.ledger_complete, finalized_at=timestamp())
            write_json(args.run / "run.json", manifest)
            result = report(args.run.resolve(), args.session.resolve())
        elif args.command == "record-check":
            manifest = read_json(args.run / "run.json")
            if args.name not in expected_evidence(manifest):
                raise ValueError("Check name must be one of the scenario's required evidence keys")
            manifest["manual_checks"][args.name] = {"status": args.status, "evidence": args.evidence, "recorded_at": timestamp()}
            write_json(args.run / "run.json", manifest)
            result = manifest["manual_checks"][args.name]
        elif args.command == "compare":
            result = compare([run.resolve() for run in args.runs])
        elif args.command == "live-readiness":
            missing = [name for name, target in (("linear_project_id", args.linear_project_id), ("notion_page_id", args.notion_page_id)) if not target or not target.strip()]
            if missing:
                print(json.dumps({"ready": False, "status": "blocked", "missing_prerequisites": missing, "remote_actions_performed": False, "note": "Explicit disposable provider target IDs are required before the live-provider test can run."}, indent=2))
                raise SystemExit(1)
            session = session_summary(args.session)
            calls = session["mcp_calls"]
            providers = {}
            for name, target in (("linear", args.linear_project_id), ("notion", args.notion_page_id)):
                allowed_tools = {"get_project", "list_issues", "get_issue"} if name == "linear" else {"fetch", "notion-fetch", "get_page", "retrieve_page"}
                matches = [call for call in calls if name in str(call.get("server", "")).lower() and call.get("tool") in allowed_tools and target in json.dumps(call.get("arguments", {})) and call.get("status") == "completed" and not call.get("error")]
                providers[name] = {"target_id": target, "connection": "observed" if matches else "unknown", "call_ids": [call.get("id") for call in matches]}
            ready = all(value["connection"] == "observed" for value in providers.values())
            result = {"ready": ready, "status": "ready" if ready else "blocked", "providers": providers, "remote_actions_performed": False, "note": "Supply real read-only calls to the explicit disposable targets before claiming connection readiness. This does not certify seeded content or authorize remote writes."}
            exit_code = 0 if result["ready"] else 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        exit_code = 2
    raise SystemExit(exit_code)
