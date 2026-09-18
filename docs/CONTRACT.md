# Rippletide pilot contract v1

This is the shared interface between the plugin and the independently packaged user-test kit. Runtime code must not depend on files outside its plugin package. The test kit does not import private router modules.

## Runtime and ownership

- Python 3.12; official `mcp==2.2.0`; Pydantic 2; `uv.lock` per package.
- Plugin source/package: `plugins/rippletide/`, import package `rippletide`, executable `rippletide`.
- Test kit: `user_tests/`, import package `rippletide_uat`, executable `rippletide-uat`.
- Primary owns plugin manifest, skill, launcher, installation, root documentation and integration scripts. Router agent owns plugin `pyproject.toml`, lock, `src/`, and `tests/`. Test-kit agent owns `user_tests/`.
- The initial pilot was built on main. The paired-evaluation enhancement is built
  in a separate worktree on `feat/routing-eval-models`; see [paired contract](PAIRED_CONTRACT.md).
  Subagents do not commit or edit each other's files.

## Project configuration

`<project>/.rippletide/config.json` is a JSON object:

```json
{
  "version": 1,
  "registry_version": "v1",
  "run_id": "example-run",
  "variant": "D",
  "log_path": "/absolute/run/router-events.jsonl",
  "preferences": {
    "prefer": {},
    "exclude": [],
    "exact_symbol_first": true
  },
  "capabilities": []
}
```

A capability has `id`, `kind` (`native`, `mcp`, `agent`), `operations` (list), `description`, `available` (boolean), `invocation` (object), and `input_schema` (JSON Schema object). Unavailable entries must never be selected. Optional `availability` contains a preflight result; only validated generated config enables fixture capabilities.

Canonical capabilities:

| ID | Operation | Invocation |
| --- | --- | --- |
| `native.filename_search` | `repository_search` | `{"tool":"exec_command","command_hint":"rg --files"}` |
| `native.lexical_search` | `repository_search` | `{"tool":"exec_command","command_hint":"rg -n"}` |
| `mcp.semantic_search` | `repository_search` | `{"server":"uat_semantic","tool":"chroma_query_documents"}` |
| `mcp.docs_search` | `knowledge_lookup` | `{"server":"uat_docs","tool":"search_documents"}` |
| `mcp.tracker_search` | `knowledge_lookup` | `{"server":"uat_tracker","tool":"search_issues"}` |
| `agent.reviewer` | `specialist_assignment` | `{"agent_type":"rippletide_reviewer"}` |
| `agent.test_specialist` | `specialist_assignment` | `{"agent_type":"rippletide_test_specialist"}` |

Tool names in invocation are logical names. Codex resolves the actual callable namespace in the session; the router does not invoke targets. Named agents must be exercised in a fresh configured Codex session before readiness is claimed.

Global preferences, when present, live at `~/.config/rippletide/preferences.json`. Task `preferred_route` overrides project `preferences.prefer`, which overrides global preferences; exclusions/availability always filter first. An explicit preferred route that is unavailable results in defer, not a silent substitute. Rules only select exact symbol/filename routes when those facts exist and relevant prior failure is absent. Ambiguous requests reach Qwen.

Exception for explicit synthetic benchmark registries: optional `fixture_mode`
defaults to false. When true, global preferences are excluded and the
`fixture_tool_use` family is permitted for registered fixture capabilities. It is
not general authorization for MCP writes. The [paired fixture contract](PAIRED_CONTRACT.md#benchmark-fixture-extension)
defines the owned transport/state restrictions and grading limits.

Variants: A disables the router and routing skill; B disables the router but supplies fixed routing guidance; C enables rule-only routing and defers unresolved choices; D enables rules plus the pinned Qwen backend. Never represent C as Qwen inference.

## MCP operations

Server: `rippletide`. Tools: `route`, `status`, `report`.

`route` accepts these flat parameters:

```json
{
  "goal": "Locate where expired sessions are rejected",
  "operation": "repository_search",
  "facts": {},
  "recent_observations": [],
  "project_root": "/absolute/workspace",
  "preferred_route": null
}
```

`facts` can contain `exact_symbol`, `filename`, `project`, and other compact task facts. At most two observations, represented as objects (e.g. `{"route_id":"native.lexical_search","outcome":"no_matches"}`). No candidate enumeration in per-decision requests. Empty/unsupported requests return a structured defer. Use the model tokenizer to enforce the 1,024-token model-input cap; trim old observations first, then defer rather than truncate essentials.

Response:

```json
{
  "decision_id": "uuid",
  "status": "selected",
  "route_id": "native.lexical_search",
  "source": "rule",
  "reason_code": "EXACT_SYMBOL",
  "registry_version": "v1",
  "invocation": {"tool":"exec_command","command_hint":"rg -n"},
  "input_schema": {"type":"object"},
  "elapsed_ms": 1.0
}
```

Defer: `status="defer"`, `route_id=null`, `invocation=null`, `input_schema=null`, `source` is `rule` or `fallback`; stable reason code. Successful model inference always selects an eligible route. Optional diagnostic fields may be added without breaking v1. A score is diagnostic, never a calibrated confidence claim.

`status(project_root)` returns readiness, model source/weight revisions, worker state, supported/available capabilities, and paths. `report(project_root, limit=20)` summarizes local decisions; actual execution is `unknown` unless external evidence was imported. Neither tool should itself be routed.

## CLI

Plugin: `rippletide setup` downloads pinned source/weights; `rippletide serve` starts STDIO; `rippletide status --project-root PATH`; `rippletide route --project-root PATH --request JSON`; `rippletide report --project-root PATH`; `rippletide preferences --project-root PATH --set JSON` applies an explicit preference update. Setup does not silently replace models. Default data directory is `~/.local/share/rippletide`, overridable by `RIPPLETIDE_DATA_DIR`.

Test kit: `rippletide-uat prepare --scenario U02 --variant D [--output-root PATH] [--plugin-root PATH]`; `serve docs|tracker --run PATH`; `check --run PATH`; `report --run PATH [--session PATH]`. Additional preflight, semantic preparation, run, intervention recording, and live-readiness commands may be added.

Each run directory contains `run.json`, `workspace/`, independent graders/results, `router-events.jsonl`, `tool-events.jsonl`, `interventions.jsonl`, and optionally `session.jsonl`. A new run must not overwrite an existing run. Generated `.codex/config.toml` connects fixture MCP servers and the router; project `.codex/agents/*.toml` defines both genuine specialist roles. A/D fixtures start from equivalent application source snapshots. Prepare must print real runnable commands and an ordinary task prompt.

## Evidence

JSONL event envelope: `schema_version=1`, `event`, `timestamp` (UTC ISO 8601), `run_id`, plus event fields. Router events use `event="routing_decision"` and include the response, request summary, model identity, and elapsed time. Tool events use `event="tool_call"` and include `server`, `tool`, `call_id`, optional `decision_id`, `status`, argument/result hashes, returned record IDs, and elapsed time. Flush events so concurrent runs remain inspectable.

Optional `phase` distinguishes `preflight` from `task` (the default). Preflight
readiness calls and decisions are retained but excluded from task routing counts
and model-execution evidence. Usage from a parent or primary-project session
alone must be marked incomplete when the task also uses specialists or another
project session.

Fixture search/fetch tools accept optional `decision_id` to correlate execution without another model turn. Agent assignments may carry the same identifier. Host session events are authoritative for native calls and real agent invocation; a router recommendation alone is never execution evidence. An unmatched or ambiguous association stays unknown.

Intervention record: `timestamp`, `category` (`required`, `setup`, `permission`, `planned_prompt`, `optional_feedback`, `inspection`), `description`, and optional `decision_id`. Initial/ordinary task prompts do not count as required interventions. Missing ledgers or missing session data must not be silently treated as zero verified interventions or zero usage.

## Pinned inference

- Engine: `harshatheg/Qwen-2.5-1B-RLCD@2af86848be75847ccb3553b0941cc51d6ef7e4e9`.
- Weights: `mlx-community/Qwen2.5-1.5B-Instruct-4bit@8b403126fc14f14cfc99bb4cfa72ecbc129ea677`.
- Persistent isolated MLX worker; explicit backend selection and verified one-token enum labels for eligible routes only. Include label descriptions in the prompt. Prevent stdout diagnostics from corrupting JSON protocol. Enforce an end-to-end two-second routing deadline after startup; readiness/loading and cold-start timing are separate. A timed-out worker cannot block later requests indefinitely.
