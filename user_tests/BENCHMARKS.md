# Five benchmark-derived user tests

Runnable local adapters and independent deterministic checks for five pinned
cases. The real Codex-vs-Rippletide comparison has **not yet been run**. Unit and
STDIO integration tests are harness verification, not measurements of the product.

## Start

From this worktree, use the existing [setup](../README.md#setup), including the
pinned CLI and installation of this branch's plugin. This implementation does not
automatically replace your personal installation. After dependencies/model setup:

```sh
npm ci --prefix tools/codex
python3 scripts/install_plugin.py
uv run --locked --project user_tests rippletide-uat benchmark run --cases B01 B02 B03 B04 B05
```

The default is one parallel pair per case, original `qwen25-rlcd` routing backend,
same Codex settings in both arms, and **no model judge**. Each attempt creates new
worktrees and databases outside source control; failures and blocked setup remain
on disk. A shared setup failure stops the suite without claiming other cases ran.
The existing paired preflight verifies the installed plugin matches this checkout;
an older cached plugin will block the run rather than silently test stale code.

For fewer initial calls, pass `--cases B01`. For repeatability follow-up:

```sh
uv run --locked --project user_tests rippletide-uat benchmark run --mode sequential --repeat 3
```

Sequential repetitions alternate arm order. Parallel runs share local hardware
and service limits, so their wall times are not isolated latency measurements.
Optional `--model` / `--effort` apply equally to both Codex arms; `--router-model`
selects an already-installed local model without changing the Codex model.

## Inspect without a paid agent run

```sh
uv run --locked --project user_tests rippletide-uat benchmark list
uv run --locked --project user_tests rippletide-uat benchmark prepare --case B05
uv run --locked --project user_tests rippletide-uat benchmark verify-sources
```

`prepare` creates tools/state/worktrees but does not call Codex or Qwen. `run`
always creates a new attempt; it never resumes or overwrites a prepared attempt.
Use the returned pair path for:

```sh
uv run --locked --project user_tests rippletide-uat benchmark check --run /absolute/pair-directory
uv run --locked --project user_tests rippletide-uat benchmark report --run /absolute/pair-directory
```

`check` exits nonzero unless both arms pass local case checks. Missing sessions
remain `unknown`, never successful abstention. For a manual protocol client,
`benchmark serve --run /absolute/pair-directory/baseline` exposes the genuine STDIO
fixture server; this is not a Codex user attempt. Do not reuse touched state for
a measured task. The runner rejects state changed during host preflight.

## Cases and grading scope

| Case | Original entry | Local deterministic checks |
| --- | --- | --- |
| B01 | BFCL `multiple_5` | Historical-coordinate tool, reference date/coordinates, successful call, unchanged state, seeded weather values in final text. |
| B02 | BFCL `irrelevance_55` | No proposed or executed cart call, nonempty completed response, unchanged cart. A blocked proposal still fails. |
| B03 | BFCL `parallel_multiple_32` | Exactly three required calls, accepted arguments, order-independent multiplicity, successful results and both city labels in final text. |
| B04 | ToolSandbox `search_reminder_with_recency_upcoming` | Clock before dependent query, one-second bound tolerance, target reminder retrieved and its exact phrase in final text, unchanged state. |
| B05 | ToolSandbox `send_message_with_contact_content_cellular_off` | Contact lookup and enabling service before successful send, either prerequisite order, one intended message, no unrelated state changes, final confirmation. |

The source catalog includes original public prompts, tool descriptions/schemas,
BFCL reference calls, immutable revisions, 17 source-file hashes and both license
texts. `verify-sources` re-extracts the selected entries and compares the catalog;
it never executes upstream Python or writes full datasets into task workspaces.
See the [source plan](../docs/BENCHMARK_USER_SCENARIOS.md) for direct upstream links.

Important disclosed adaptations:

- These first graders are **local reference-call/milestone contracts**, not the
  official BFCL AST checker or ToolSandbox evaluator. Official scores stay null.
  An official-scorer adapter remains follow-up work; no leaderboard claim is made.
- BFCL dictionaries/tuples/floats map to JSON objects/arrays/numbers. Function dots
  map to double underscores on the MCP transport. Weather data is synthetic.
- ToolSandbox uses a reduced synthetic state, fixed UTC clock and local handlers;
  text search uses case-insensitive substring matching, not upstream fuzzy search.
  It does not execute upstream state machinery or ROUGE/milestone similarity.
- B04 exact final-content and B05 `sent`/`Fredrik` confirmation checks are stricter
  local assertions and may reject valid paraphrases. B03 city labels do not prove
  every numerical prose claim. The report exposes individual checks and scope.
- A recovered early send error is retained but is not a fabricated unique-order
  failure. Duplicate actual messages fail the extra local safety assertion.

## Evidence and safety

`benchmark-report.md` adds case-level correctness to the existing `report.html`,
`report.md`, and `report.json` metrics/timelines. `benchmark-results-private.json`
and `evidence-private.json` retain proposals, actual calls, arguments, model/rule/
fallback decisions, returned data, final response and metric coverage. The fixture
database stores transactional before/after hashes and server-generated call IDs.
Only unambiguous same-tool/same-arguments host result IDs verify executions.

Tool choice, argument correctness, state/task checks, router recommendations and
routing compliance are separate. In particular, B02 may expose the existing
`ONLY_CANDIDATE` rule: its wrong cart recommendation is recorded even if Codex
declines to execute it. Rule-only or absent-router outcomes do not prove Qwen
contribution. Context-dependent ToolSandbox recommendations without a unique
ground-truth next choice remain ungradable.

Time/tokens/interventions reuse the paired evidence contracts. Setup/cold load is
separate; missing tokens are not zero; no monetary saving is inferred. Grading
attempts are archived under `benchmark-grades/`; the latest summary is regenerated
without removing old attempts or human audits. Changed fixture/grader code cannot
silently regrade an old prepared run; source and implementation hashes must match.

Both task workspaces exclude source catalogs, expected answers and graders.
Model-readable instructions also prohibit inspecting private fixture files;
this is not an OS-level secrecy claim. Out-of-scope task tools invalidate local
acceptance; ambiguous/missing evidence stays unknown.

Fixture write permissions require the exact built-in server command, case tool
catalog and owned state directory. Remote URLs, arbitrary commands, extra agents,
credentials and answer-revealing preferences are rejected in fixture mode. Normal
paired tests keep their existing read-only remote MCP policy. Global routing
preferences are intentionally excluded only in explicit fixture mode.

The hook/session integration reuses the pinned host and documented
[Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[non-interactive sessions](https://learn.chatgpt.com/docs/non-interactive-mode).

## Developer verification

```sh
uv run --locked --project user_tests pytest user_tests/tests/test_benchmarks.py -q
uv run --locked --project user_tests pytest user_tests/tests -q
uv run --locked --project plugins/rippletide pytest plugins/rippletide/tests -q
```

Tests cover golden/negative trajectories, real STDIO calls, schemas/mutation hints,
state isolation, source provenance, fixture-scope rejection, missing telemetry and
report correlation. Synthetic host transcripts are clearly unit-test fixtures,
never entries in the human [experiment tracker](../docs/BENCHMARK_EXPERIMENT_REPORT.md).
