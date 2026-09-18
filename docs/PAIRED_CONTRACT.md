# Paired-run implementation contract

This extends the v1 routing contract without changing its three public MCP operations.
Implementation is isolated on `feat/routing-eval-models`, based on main at
`c8c59b074d47a1406d3a958137ea19a274319aea`.

## Boundaries

- Model selection is process configuration (`RIPPLETIDE_MODEL` or `serve --model`),
  never a model-generated routing argument. Default: `qwen25-rlcd`.
- Other aliases: `qwen3-0.6b`, `minicpm5-2b`, `qwen3.5-4b`. One worker/model per
  server. Existing model artifacts and default behavior remain compatible.
- Hooks use `RIPPLETIDE_RUN_DIR` for owned evidence/state; absent this, use a
  project-scoped local data directory. Router logs retain their existing format
  with added bounded `request` context and selected model identity.
- Hook events are JSONL in `hook-events.jsonl`, with `schema_version: 1`,
  `event`, `timestamp`, `session_id`, `transcript_path`, `turn_id`, `call_id`,
  `tool_name`, `tool_input`, `phase`, plus a decision ID when known. Event names:
  `tool_proposed`, `routing_authorized`, `routing_blocked`, `tool_completed`,
  `routing_receipt`, `hook_error`, `uncovered_tool`. Decisions are not executions.
- Registered native searches, information MCPs and named specialists are
  covered. Other actions are observed, not silently claimed to be routed.

## Pair artifacts

Each fresh output directory contains `pair.json` (schema_version 1) with:

```
run_id, repo, base, base_sha, prompt, mode, router_model, created_at,
profile, arms: {baseline: ARM, rippletide: ARM}
```

Each ARM has `run_id`, `workspace`, `branch`, `status`, `wall_seconds`,
`session_path` (CLI JSONL), `parent_rollout`, `child_rollouts` (list),
`exit_code`, `acceptance` (independent command results), `router_events`,
`hook_events`, `interventions`, and `settings`. Unavailable fields are null, not
invented. `profile` contains no credentials. Status distinguishes setup-blocked,
running, completed, failed, timed_out and cancelled; completion is not correctness.
Paths may be absolute; reports redact presentation paths.

## Package boundaries

- `paired.py` and `profiles.py`: configure/run CLI, worktrees, private Codex
  profiles, process control, independent checks, host/phase/evidence capture.
- `paired_evidence.py`: `report_pair(run: Path) -> dict` writes `report.json`,
  `report.md`, `report.html` using `pair.json`, raw events and correctness records.
  May be called again after grading/audit. Does not import router internals.
- `correctness.py`: `grade_pair(run: Path, *, codex: str, environment: dict,
  model: str | None = None, effort: str | None = None, timeout: float = 180) -> dict`
  runs a separate read-only judge, stores `correctness.json` and judge evidence.
  `audit_grade(run: Path, call_id: str, verdict: str, reason: str) -> dict`
  appends human audit records without replacing original grades.
- The paired runner CLI owner wires configure/run/audit and invokes grading then
  reporting. Standalone fixture commands remain compatible.

## Evaluation rules

Task correctness, tool-choice correctness, execution success and routing
compliance are independent. Verdicts: correct/incorrect/uncertain/ungradable.
Grade both arms against the same frozen rubric, using only information available
before each choice. Multiple acceptable tools are valid. Automated grades are
provisional; fixture-approved and human-reviewed grades have separate provenance.
No hidden reasoning is requested. Judge costs are separate from execution costs.

Usage includes parent and children without duplicated inherited history or
cumulative-resume snapshots. Missing coverage stays incomplete. Raw evidence is
private; presentation outputs are escaped/redacted. External provider access is
read-only. Failures, interventions, fallback and unsupported hook paths remain
visible. Neither a successful process nor a successful final patch proves routing
or benchmark success.
