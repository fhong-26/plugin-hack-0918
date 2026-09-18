# Routing checks and paired evaluation — 2026-09-18

This is implementation evidence, not the PRD's full benchmark. The original
[pilot report](PILOT_RESULTS.md) remains historical and unchanged. All enhancement
source work was developed on `feat/routing-eval-models`, in a separate worktree
based on main `c8c59b074d47a1406d3a958137ea19a274319aea`. These results were
collected before the implementation was committed and merged.

The defer counts and model-choice descriptions below record that historical run.
The current implementation no longer offers defer as a successful model-inference
choice; operational and rules-based fallbacks remain.

## What is implemented

- Installed-plugin routing skill plus single-use, session/turn-scoped hook receipts
  for registered native searches, information MCP tools and named specialists.
- A paired runner for an ordinary task in two new branches/worktrees at one frozen
  base SHA; approved tools and task settings match. Neither arm edits the source
  checkout. Each attempt retains its own evidence, including failures.
- Read-only MCP onboarding, real named specialist readiness, isolated credentials
  references, bounded correction/timeout handling, and independent check commands.
- Private full traces plus redacted Markdown/HTML/JSON reports. Tool selection,
  execution, task checks and routing compliance are separate dimensions.
- Independent per-choice Codex grading with a frozen rubric, prior-only context,
  provisional labels and append-only human audits. Judge usage is separate.
- Four pinned local MLX model options, retaining the original RLCD default.

## Real local model checks

All four models were downloaded, checksum-verified and actually loaded on the
reference Apple Silicon machine. Alternative models use their native templates,
disabled thinking and constrained single-token readout; none replaces the default.

| Backend | Expected choices in five development cases | Defers | Repeated warm route time |
| --- | --- | --- | --- |
| Original RLCD (default) | 5/5 | 0 | 61–62 ms |
| Qwen3 0.6B | 5/5 | 0 | 41–43 ms |
| MiniCPM5 2B | 3/5 | 2 | 81–85 ms |
| Qwen3.5 4B | 5/5 | 0 | 154–172 ms |

These are development/contract cases, not held-out accuracy or end-to-end timings.
An initial Qwen3 prompt produced five defers. That evidence remains retained; the
prompt was clarified to distinguish selecting a tool from performing the task.
No defer choice was removed or forced into a selection. Repeated label stability
does not prove an entire Codex session is deterministic.

Local artifacts: implementation-worktree `.uat-runs/models-v2/`. The public native
and MCP integration is at
`.uat-runs/models-v2/public/U02-D-dba8ed0158e3/public-integration-evidence.json`.
Pinned artifact identities are listed in the [plugin README](../plugins/rippletide/README.md).

## First real parallel pair

Run: `pair-20260918T130733-41d5a02894`, under the default local UAT runs directory.
Task: fix the seeded session-expiry boundary bug using genuine documentation and
tracker MCPs, native search and a configured specialist. The external five-case
grader was frozen outside both workspaces; the original implementation failed
its exact-expiry assertion before the task.

| Measurement | Codex alone | Codex + Rippletide |
| --- | --- | --- |
| Task wall time | 35.605 s | 62.048 s |
| Codex input tokens (parent + child) | 187,285 | 370,624 |
| Cached input (subset of input) | 155,381 | 330,762 |
| Output tokens | 1,334 | 2,450 |
| Total tokens | 188,619 | 373,074 |
| External acceptance | 5/5 passed | 5/5 passed |
| Required human interventions | 0 | 0 |
| Qwen model-selected routing decisions | Not applicable | 6 |
| Blocked unrouted attempts | 0 | 1 |

The enabled arm was **about 74% slower in this one parallel case**. It made six
real Qwen selections leading to native search, information MCP calls and a named
test specialist. Routing requests took about 80–168 ms; the whole Codex interaction
cost is larger than model inference alone. Setup and grading are separate.

The trace also contains repeated information searches and a document-fetch attempt
without a fresh receipt. The guard blocked that attempt; the task continued and
passed its behavioral checks. This is not perfect routing compliance or proof of
optimal tool choice. The report retains the blocked call, provisional correctness
grades and all ungraded choices rather than converting task success into a pass
on every dimension.

The first in-flight evaluator used a batch of cards. Its raw evidence is retained,
but the current report is regraded with separate per-choice evaluator processes to
prevent one card from revealing later evidence to another. The default cap is 12
choices; omitted choices remain ungradable, not silently correct.
The retained isolated sample graded eight baseline and four enabled choices;
all twelve were provisionally correct, with 25 other choices ungraded. It is an
unbalanced exploratory sample, not an accuracy comparison. Future sampling is
balanced by arm and prioritizes registered native/MCP/agent choices. Judge time
was 26.982 s, with 157,082 input and 1,241 output tokens, excluded from task totals.

## Real Linear / Koesio pair

Run: `pair-20260918T131157-9e90aae84f`, from Koesio main
`a33843bfec4abefaef0b6143a9b15ab4953ba7d1`. Both arms used real read-only Linear
access, the same task and distinct fresh branches/worktrees. Notion was explicitly
unavailable. Only synthetic/local application checks were authorized; the source
checkout and its pre-existing documentation edits remained unchanged.

| Measurement | Codex alone | Codex + Rippletide |
| --- | --- | --- |
| Task wall time | 143.635 s | 49.310 s, stopped early |
| Independent queue acceptance | Passed | Failed |
| Input tokens | 1,042,795 | 309,537 |
| Cached input (subset) | 946,102 | 266,697 |
| Output tokens | 6,608 | 1,810 |
| Total tokens | 1,049,403 | 311,347 |
| Parent/child usage coverage | Complete | Complete (no task specialist ran) |

**The enabled attempt did not fix the bug.** Its model repeatedly selected
`linear.get_issue` when `linear.list_comments` was required, including after the
goal and observations explained the mismatch. The guard blocked the comments
calls and the task stopped. Its smaller elapsed time/token total is therefore
**not a speed or cost win**. No human rescued either attempt; the stopped attempt
remains in the denominator and cannot count as autonomous successful completion.

The baseline passed two independently maintained queue-admission checks and used
a real specialist. Passing these checks does not certify its whole patch or make
it production-ready; the uncommitted worktree is retained for review. There were
no commits, pushes, PRs, Linear writes, or production calls.

The isolated tool-choice judge sampled six choices per arm (12 of 42 total);
the remaining 30 are explicitly ungradable. Its 29.419 s and 183,951 input / 1,382
output tokens are separate evaluation overhead. Automated grades are not a
substitute for the clear end-to-end failed acceptance result.

This run also revealed a shell recognizer error on quoted prose in a documentation
here-document. That error remains visible in the historical trace. The current
guard now records unparseable shell wrappers as unsupported coverage rather than
blocking unrelated edits; a regression test covers the fix. The default model's
incorrect Linear selection remains a known limitation, not silently repaired by
a test-specific preference or overridden score.

The two local graders above were inspected as standalone external acceptance
programs, not merely project tests with an external configuration file. New runs
require explicit `--independent-check-argv` approval before assigning independent
provenance; ordinary project checks remain provisional.

## Verification boundaries

Final checks:

| Check | Observed result |
| --- | --- |
| Plugin runtime suite, including actual loading of all four models (`pytest --run-model`) | 80 passed |
| User-test kit, runner and evidence/grader tests | 106 passed |
| Root script tests | 17 passed; 2 live-host controls skipped by default |
| Opt-in host evidence tests | 4 passed: 2 helpers and 2 genuine fresh-session controls |
| Plugin manifest, routing skill and whitespace validation | Passed |

The strict positive host control verifies correlated successful native and genuine
probe MCP execution plus a completed child agent. The negative control checks an
actual host denial and that a would-be file-write sentinel was not created. This
does not rely solely on a hook logging its intent. The final here-document fix
was then covered by its added regression and the complete 80-test runtime suite.

Hook checks were exercised in fresh Codex 0.155.0 sessions. A deliberately absent
model directory tests visible fallback without substituting another model. This
control is not counted as model-selected execution evidence. An initial failed
host-test prompt and its logs remain retained; the corrected positive and negative
controls are separate attempts.

Hooks recognize explicit registered calls, not arbitrary shell-program semantics.
Unsupported/unregistered paths are reported outside coverage. Hooks do not replace
Codex permissions and are not a security boundary. Ordinary direct file reads,
edits and test commands are not routed.

Token totals require verified parent-and-child coverage. Cached input is a subset,
not extra input to add again. Missing usage remains incomplete. No dollar savings
are inferred from token counts; neither local energy cost nor subscription/API
billing is measured here. Repeated sequential trials are still needed for fair
performance and consistency conclusions.

The three alternative backends have real local contract coverage, but the paired
task evidence above uses only the default. Dedicated Notion tests and the full
40-task benchmark remain later milestones. No full-product speed, cost, correctness
or intervention target is declared achieved.

## Reproduce

See the [short startup commands](../README.md#start-a-user-test) and
[project onboarding](../user_tests/README.md#test-an-existing-project).
Keep raw `evidence-private.json`, rollouts and hook/router JSONL local; use the
allowlist-redacted `report.html`, `report.md` or `report.json` for presentation.
