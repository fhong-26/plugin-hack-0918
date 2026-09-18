# Rippletide user-test kit

This package supplies real local MCP tools, real Codex specialist configurations,
fresh application projects, independent graders, and evidence reports for U01–U09
in the PRD. It is independent of the router implementation.

The documentation and tracker servers query separate seeded SQLite databases.
They return current and historical records with provenance; they do not return
prewritten tool-choice answers. The specialist templates configure actual Codex
agents. No model or specialist result is synthesized by this package.

## Test an existing project

The paired runner runs an ordinary task in **two new branches/worktrees from the
same resolved commit**: Codex alone and Codex + the installed Rippletide plugin.
The original checkout, including dirty files, is not changed or copied. The base
must already exist locally; no implicit pull occurs. Pair runs are stored outside
the repository under `~/.local/share/rippletide/uat/runs/` by default.

Install the [root prerequisites](../README.md#setup), then configure once:

```sh
uv run --locked --project user_tests rippletide-uat configure --repo /absolute/project \
  --bootstrap-argv '["uv","sync","--locked"]' \
  --check-argv '["uv","run","pytest"]'
uv run --locked --project user_tests rippletide-uat run --repo /absolute/project \
  --task 'Fix the expiry-boundary bug and add regression coverage.' --base main
```

Commands are JSON argument arrays, not shell strings; choose commands appropriate
to the project. Repeat either option for several commands. `configure --replace`
explicitly updates an existing local profile. Missing checks leave task correctness
ungraded. Tests inside the working project can be edited by the task agent, so
their results are provisional. For stronger acceptance, explicitly approve an
absolute external standalone grader with `--independent-check-argv`, using
`{workspace}` for the target. The runner freezes and hashes that grader outside
both presented workspaces. An external config/data file alone does not make a
project-owned test independent; ordinary `--check-argv` stays provisional.

Default tools are native filename/text search plus real reviewer and test
specialists. Both arms receive the same tools, task and Codex settings. The local
routing model is separate from the Codex task model:

```sh
uv run --locked --project user_tests rippletide-uat run --repo /absolute/project \
  --task-file /absolute/task.md --router-model qwen3-0.6b --mode sequential --repeat 3
```

`parallel` is the default; its wall times include shared-machine contention. Use
repeated sequential pairs before drawing performance conclusions. Fresh attempts
never overwrite previous evidence. Setup, preflight and post-run judging are not
included in task execution time/token totals. Missing child usage remains unknown;
it is not counted as zero. No price estimate is inferred from token count alone.

### Linear and other information MCPs

Personal MCPs are **not** inherited automatically. Supply an approved JSON file
with `--tool-config /absolute/approved-tools.json` when configuring the project.
Start with [the read-only Linear example](examples/linear-readonly.example.json),
replace `YOUR-ISSUE-ID`, and run `configure` from this repository root so its
specialist template paths resolve. Add your project's bootstrap/check commands.
Only read-only tools explicitly listed in `enabled_tools` may be connected. Each
routable MCP capability needs an `id`, `kind`, `operations`, `description`,
`invocation` (`server`, `tool`) and `input_schema`. The runner verifies actual tool
schemas and availability before the task. For a Codex-managed OAuth connection,
`mcp_preflight` declares one approved read call per server. The actual host must
complete it in both arms using its existing authentication; supplied schemas
are then labeled unverified rather than falsely attributed to `tools/list`.
Include all desired specialists in this
profile too; custom tool configuration replaces, rather than merges, the default.

Example server entry (inside `mcp_servers`) for an explicitly provisioned token:

```json
{
  "linear": {
    "url": "https://mcp.linear.app/mcp",
    "bearer_token_env_var": "RIPPLETIDE_LINEAR_TOKEN",
    "enabled_tools": ["get_issue", "list_comments"]
  }
}
```

Do not put credentials in the JSON, repository, task prompt or command arguments.
Authentication references are temporary; secrets are never copied into reports.
Missing credentials or unsuccessful OAuth preflight must produce a setup-blocked
result, not an apparent test pass. This is a read-only ticket experiment: no
ticket updates, external writes, commits, pushes or PRs are performed.

### Reports and correctness

Open `RUN/report.html` for a presentation-safe comparison. Markdown and JSON
versions are generated alongside it. They distinguish:

- **Tool-choice correctness:** Was this a reasonable available capability for the
  immediate goal? Several tools can be valid. Automated grades are provisional.
- **Execution success:** Did the actual invocation succeed? Missing status is unknown.
- **Task correctness:** Did the configured independent or project checks pass?
- **Routing compliance:** Did a registered call follow its own preceding receipt?

The independent post-run judge uses the same frozen rubric for both arms, with
anonymized decision-time context in separate per-choice calls, so one card cannot
reveal a later observation to another. The default budget covers up to 12 choices
with two judge processes at a time; remaining choices are explicitly ungradable.
Its token/time totals are separate. Missing
context, a missing result, or an omitted grade stays uncertain/ungradable. This
is not a claim that a model judge can prove optimal tool selection.

Raw transcripts, full bounded router requests, hook records and normalized
`evidence-private.json` are private local evidence and can contain source/ticket
content. The default report omits prompts, arguments, results, credentials, paths
and custom tool names; review any raw files before sharing them. A decision trace
is an observable request/response and call, not hidden model reasoning.

```sh
uv run --locked --project user_tests rippletide-uat report --run RUN
uv run --locked --project user_tests rippletide-uat audit-grade --run RUN \
  --call-id 'CHOICE_ID_FROM_PRIVATE_EVIDENCE' --verdict correct \
  --reason 'The documented authoritative source was available at this point.'
```

Human audits append to the original automated grades. Failed/stalled attempts and
required interventions remain visible. A successful CLI exit alone never proves
task correctness, low intervention, or a speed/cost advantage.

## Install and prepare

Run from the repository root:

```sh
uv sync --locked --project user_tests --group dev
uv run --locked --project user_tests rippletide-uat prepare --scenario U02 --variant D
```

The JSON output identifies the new run, its workspace, task prompt, and commands.
Each run is a new nonoverwriting directory under `.uat-runs/`. Pass
`--output-root PATH` and optionally `--run-id NAME` to choose another location.
Never reset an old attempt: prepare a fresh one and retain its evidence.

`prepare` performs real MCP initialization, tools/list, search, and fetch checks
before enabling the documentation and tracker routes. It also configures native
search if `rg` is installed. Qwen setup belongs to the plugin's `rippletide setup`.
The semantic and agent routes remain unavailable until their own checks pass.

The generated project includes `.codex/config.toml`, two genuine specialist
TOMLs, and project preferences. C/D copy the public routing skill into the
project's `.agents/skills/`; A/B do not. All variants disable any installed
`rippletide@personal` instance and use only explicitly configured pilot routing.

Host configuration behavior varies by Codex release. Named specialists require
a host that exposes custom `agent_type` selection. Both standalone agent files
and compatible explicit role bindings are generated. Start the process with its
actual working directory set to the generated workspace. Do not assume `-C` or
`--ignore-user-config` loads project settings: verify the active tool catalog.
The repository's `scripts/run_pilot.py` handles the verified CLI configuration
path and captures actual sessions. The local desktop can also be used manually.

## Readiness before a measured task

```sh
uv run --locked --project user_tests rippletide-uat preflight --run RUN
uv run --locked --project user_tests rippletide-uat prepare-semantic --run RUN
```

Semantic preparation invokes the separately locked `integrations/chroma` CLI.
It indexes real project sources, verifies the upstream Chroma MCP protocol, and
then adds its returned server configuration and actual tool schema. An empty
new-project workspace has no source to index; prepare semantic retrieval after
the initial application exists. Failure leaves semantic routing unavailable.

Before enabling agents, give `RUN/agent-preflight-prompt.txt` to a fresh Codex
session in the generated project. This is a setup task that explicitly invokes
both named agents and waits for them. Then import its real transcript:

```sh
uv run --locked --project user_tests rippletide-uat verify-agents \
  --run RUN --session AGENT_PREFLIGHT_RAW_JSONL
```

Both a successful role-specific spawn and completion are required. Current
`codex exec --json` output can omit the chosen agent role; use the corresponding
raw Codex rollout JSONL when necessary. The parser accepts either format, but
does not infer invocation from a model saying that an agent ran. Setup calls do
not count as Qwen routing evidence or as normal task attempts.

## Run the user scenarios

Start a fresh Codex session in `RUN/workspace` and supply the exact ordinary
prompt from `RUN/prompt.txt`. Do not mention Rippletide or the expected route.
Where present, supply `RUN/followup.txt` as the planned follow-up. Capture the
actual host session and check the result independently.

| Scenario | Prepared project and assessment |
| --- | --- |
| U01 | Empty application workspace plus connected taskboard requirements. Build, run `check --stage starter`, send the filter follow-up, then `check --stage filter`. Perform and record the browser walkthrough. |
| U02 | Session service with an expiry-boundary bug; connected `SESSION-17` issue and current published policy. `check` tests five independent behaviors. |
| U03 | Both services contain overlapping historical/current requirements. The authoritative source is documentation for session-alpha and an approved issue for session-beta. Review citations and meaning. |
| U04 | A real candidate patch fixes expiry but accidentally drops revocation. Two prompts exercise the test specialist and reviewer; retain actual spawned-agent evidence and assess their findings. |
| U05 | Existing project needs requirements retrieval, a fix, verification, and specialist review. `check` grades the resulting behavior. |
| U06 | Two independent workspace copies with distinct saved preferences. Run comparable prompts in fresh sessions, explicitly save one correction, and verify persistence and isolation. |
| U07 | Require `--failure docs`, `tracker`, `reviewer`, `test_specialist`, or `model`. Missing tools/roles are genuinely disconnected; model failure uses an empty isolated model-data location and requires D. Observe fallbacks and absence of loops/false execution claims. |
| U08 | Finish an ordinary task, then request the routing report. Compare it with observed calls. |
| U09 | Prepare identical copies for A/B/C/D with `--comparison-scenario U02` or `U05`. Use equal Codex settings and compare outcomes, usage, calls, and interventions. |

The session fixture exposes `SessionStore` and `validate_identity`. Its public
tests miss the exact deadline bug. The external grader checks before, exactly
at, and after expiry, plus revoked and missing sessions. U04 deliberately has a
different defect. Independent graders live outside the working project; all
variants instruct Codex not to inspect parent/grader/plugin implementation data.

The taskboard grader exercises real HTTP behavior and a process restart. It
checks task creation/listing, completion, invalid requests, persistence, and the
completed filter when requested. It does not substitute for the browser check.

## Record evidence and interventions

```sh
uv run --locked --project user_tests rippletide-uat check --run RUN
uv run --locked --project user_tests rippletide-uat intervention --run RUN \
  --category planned_prompt --description 'Initial ordinary task prompt'
uv run --locked --project user_tests rippletide-uat intervention --run RUN \
  --category required --description 'Had to remind Codex to use the router'
uv run --locked --project user_tests rippletide-uat report --run RUN --session SESSION_JSONL
```

Use categories `required`, `setup`, `permission`, `planned_prompt`,
`optional_feedback`, or `inspection`. Record an unplanned correction even when
volunteered. Mark the ledger complete only after reviewing the actual run:

```sh
uv run --locked --project user_tests rippletide-uat finalize --run RUN \
  --session SESSION_JSONL --outcome success --ledger-complete
```

Outcomes also include `failed`, `stalled`, and `abandoned`. A success declaration
alone cannot pass missing application checks or missing scenario evidence.
`record-check --run RUN --name KEY --status passed|failed|blocked|unknown
--evidence TEXT` records scenario assertions that require review. `report` lists
the permitted keys; machine-observed facts cannot be overridden by annotations.

Fixture tools accept `decision_id` in the same actual call and write server-side
events. Agent assignments may carry that ID; role-specific spawn and completion
provide the evidence. Native calls often lack a decision ID. After inspecting a
completed transcript, link an unambiguous call explicitly:

```sh
uv run --locked --project user_tests rippletide-uat correlate --run RUN \
  --session SESSION_JSONL --decision-id DECISION --call-id HOST_CALL_ID \
  --note 'Reviewed this routing response followed by this exact search call'
```

Correlation validates the real host call and target; the transcript hash must
remain unchanged. Unmatched/ambiguous calls stay unknown. Server preflight calls
are excluded. A recommendation alone cannot count as execution. Missing usage,
session evidence, or an incomplete intervention ledger stays unknown, not zero.

`compare --runs RUN_A RUN_D ...` includes failed/stalled attempts and reports the
zero-intervention completion rate and interventions per attempted run. Compare
the same normal-operation cohort and settings; deliberate U06/U07 corrections
and failure injection are assessed separately. The PRD goals remain ≥90%
successful runs without required intervention, mean ≤0.2, and no increase over
Codex alone. This package does not claim those goals have been achieved.

## Later third-party pass

Local services are first; a separate pilot uses real Linear and Notion tools
against specifically designated disposable test locations. Do not use personal
data implicitly. Given explicit IDs and a transcript of read-only provider calls:

```sh
uv run --locked --project user_tests rippletide-uat live-readiness \
  --linear-project-id LINEAR_TEST_PROJECT --notion-page-id NOTION_TEST_PAGE \
  --session PROVIDER_SESSION_JSONL
```

This command examines only supplied evidence. It makes no network calls and no
remote writes. Missing provider access remains unknown; local tools are not
silently substituted for this pass. Seeded-content equivalence and the actual
U02/U03/U05/U09 outcomes must still be checked.

## Developer verification

```sh
uv run --locked --project user_tests pytest -q
```

Tests exercise actual subprocess MCP services, meaningful seeded bug/fix
grading, fresh snapshots, isolation, failure preparation, and conservative
evidence parsing. Synthetic host-event samples exist only in unit tests and are
explicitly not real-session UAT results. The fixture kit covers the pilot; the
PRD's later 200-decision/five-repository benchmark is a separate evaluation.
