# Local pilot results — 2026-09-18

## Outcome

The local runtime, installable Codex plugin, real test tools, specialist agents,
and repeatable user-test runner are implemented. Real Qwen decisions have led to
verified native search, MCP search, and Codex specialist execution.

**This is a working pilot, not a passed product benchmark.** Some Codex sessions
still omit eligible routing, Qwen sometimes chooses the wrong specialist/source,
and inspection can misdescribe an omission. The low-intervention completion and
efficiency targets are not established. The PRD's full definition of done remains
open; do not interpret passing code tests as passing U01–U09 in full.

## Reproduction and environment

Reference hardware: Apple M5, 24 GiB memory, Apple Silicon macOS. Python 3.12.13,
uv 0.11.9, MCP SDK 2.2.0, MLX-LM 0.31.3. The actual Codex smoke sessions used CLI
0.132.0, GPT-5.5, inherited/default reasoning, workspace-write sandbox and no
interactive approvals. Specialists inherited their parent's model settings.

The current desktop-bundled CLI exposed a different generic-agent tool surface;
the pilot therefore verified named `agent_type` assignments through compatible
`agents.<role>.config_file` bindings. The kit also ships standalone agent files.
Do not silently assume a newer host supports the same invocation interface.

The runner explicitly passes generated project configuration to the CLI because
`--ignore-user-config` also omitted project layers in the tested CLI. It registers
the public routing skill in C/D, isolates A/B, and never substitutes a fake MCP
response or canned specialist. The installed-package smoke is separate from the
development-package comparison.

The personal marketplace installation, normal-settings discovery of the
namespaced routing skill, and installed MCP `initialize`/`tools/list`/`status`
were verified. Two initial isolated installed-plugin attempts did not discover
Rippletide and are marked failed despite fixing the application. In CLI 0.132.0,
the [plugin loader](https://github.com/openai/codex/blob/rust-v0.132.0/codex-rs/core-plugins/src/loader.rs#L351-L358)
uses [user-only configuration layers](https://github.com/openai/codex/blob/rust-v0.132.0/codex-rs/config/src/state.rs#L290-L307),
so `--ignore-user-config` plus CLI plugin overrides cannot enable discovery.

The corrected installed-package path creates a private, mode-0700 temporary
Codex home with a minimal user-configuration layer and uses the normal plugin
install command. Preflight verifies only Rippletide is registered, and the
namespaced skill comes from that private installed cache. The development
skill/config are archived outside the test workspace, so they cannot stand in
for the installation. No personal services or model settings are copied.
Authentication is reused by temporary reference when needed, never printed or
copied; that reference is removed after the run. Missing discovery fails closed
before any task/model call. This is separate from the development-package A–D
comparison.

The corrected installed attempt **U02-D-17e77e6c7bdb** completed in 50.499 seconds:
five independent acceptance checks and five executed unit tests passed, with
zero required interventions. Qwen selected tracker search (`91a5eff6-7f26-4702-b04a-535ee90f4ced`)
and documentation search (`f084eeb2-787f-412e-aced-c1866bff12df`), both verified
against subsequent host calls and fixture logs. Routing took 205 ms and 125 ms
with the same worker. Its initial native inventory was still unrouted; this
does not certify universal routing compliance. A preceding private-home attempt
failed authentication and remains failed in the ledger; the runner now checks
authentication before preparing a task. The successful run's temporary auth
reference was verified removed, with the original credential file untouched.

```sh
uv run --locked --directory plugins/rippletide pytest --run-model -q
uv run --locked --directory user_tests pytest -q
RIPPLETIDE_SEMANTIC_INTEGRATION=1 uv run --locked --directory integrations/chroma pytest -q
python3 -m unittest discover -s tests -q
python3 scripts/run_pilot.py --scenario U02 --variant D
python3 scripts/summarize_pilot.py
```

Observed verification: **32 runtime tests, 34 test-kit tests, 6 Chroma tests,
and 15 runner/accounting tests passed**. Plugin and skill validators also pass. The runtime
tests include actual pinned inference and public MCP/tool execution, not only
mocked decisions. Chroma tests query real local embeddings and verify ranking,
source-line metadata, and stale-chunk refresh.

## Model identity and latency

| Artifact | Exact revision |
| --- | --- |
| `harshatheg/Qwen-2.5-1B-RLCD` engine source | `2af86848be75847ccb3553b0941cc51d6ef7e4e9` |
| `mlx-community/Qwen2.5-1.5B-Instruct-4bit` declared weights | `8b403126fc14f14cfc99bb4cfa72ecbc129ea677` |

The weights' SHA256 is checked during setup. Artifact paths, source hashes, and
provenance stay outside Git under the local model-data directory. The backend
does not substitute another model. Pilot capability labels are meaningful,
verified single tokens; `defer` is a real choice. Scores are uncalibrated candidate
softmax diagnostics, never confidence guarantees.

Initial setup loaded/warmed in about 4.47 seconds. A later public integration run
reached readiness in 1.06 seconds; five warm routes took 61–70 ms using the same
worker. Its cold first request deferred in 1.44 ms. These are small observed
samples, not latency guarantees or evidence of complete-task savings. A full
worker pipe is separately tested: nonblocking writes share the two-second
deadline and cannot hang before the response wait.

Retained developer evidence:
`.uat-runs/developer-integration/U02-D-7dc2c2e2fad6/public-integration-evidence.json`.
These subprocess/MCP tests are not counted as Codex user-task success.

## Verified handoffs

| Category | Actual Codex evidence |
| --- | --- |
| Native | U01-D-3dccfe7f1227: Qwen decision `eb029fa1-4c9c-4746-96d2-2e5d8e114c99`, then host call `call_ue1Jtq24c09qqv539BOiWvcr` ran the matching `rg -n` persistence search and exited 0. Independently reviewed correlation is saved. |
| MCP | U03-D-804515aff6fb and U09-D-77b98d03d162: Qwen-selected searches match successful host calls, decision IDs, normalized arguments, fixture-server logs, and authoritative returned records. |
| Agent | U04-D-272309259cba: actual Qwen-selected test specialist. U09-D-fe1860e338d1: reviewer decision `3ebacb02-7be0-459c-92ff-8185a75d01e3` maps to `call_XEIojsG4FLsj1wVxCd8GNUI2` and completed child `01a0b413-64da-7750-8360-ece900146eda`. |

The U09-D native search preceded its routing recommendation, so that decision
remains **unverified**. A specialist reused its parent assignment's decision ID
on one documentation call; that child lookup remains unverified too. Neither is
repaired by inventing telemetry or by asking an extra model turn to explain it.

## User scenarios

| Scenario | Observed result and qualification |
| --- | --- |
| U01 | New task tracker passed independent HTTP create/list/complete/filter/error/persistence checks. A real browser walkthrough created a task, completed it, hid it under Active and showed it under Completed. Only browser error was a missing favicon. Native Qwen handoff verified. |
| U02 | Existing expiry bug fixed; independent before/equal/after/missing/revoked checks pass. Real tracker and docs retrieval observed. Some attempts had routing omissions, kept separately. |
| U03 | Both project scopes answered with correct authoritative sources: published `DOC-SESSION-2` for alpha and approved tracker `BETA-42` superseding `DOC-BETA-1` for beta. |
| U04 | Real specialists identified missing exact-boundary coverage and the deliberate revocation regression. Qwen initially picked the test specialist for the later code-review request; Codex corrected it autonomously through the explicit task preference. This is a first-choice quality failure, not perfect routing. |
| U05 | Mixed native/MCP/reviewer workflow produced a passing fix. Real Qwen reviewer execution verified; an initial native inventory was not routed. Semantic search was genuinely indexed/registered but was not selected in that workflow. |
| U06 | Both project settings and explicit correction persisted with scope isolation. Strict workflow review found an ignored initial filename preference/pre-routing searches; this is not a full end-to-end preference pass. |
| U07 | Missing-model requests returned fast fallbacks for distinct goals; Codex continued and obtained a real reviewer. A separate tracker-disconnected run used documentation, did not call the missing service, and disclosed the limitation. Its native-routing omissions remain a workflow failure. |
| U08 | Task explanation completed before optional inspection. Inspection incorrectly called registered native searches out of scope in one attempt; a later attempt still omitted an inventory from its routing account. Report-accuracy acceptance failed. |
| U09 | A–D on U02 and A/D on U05 all passed independent application checks. Settings/snapshots were reviewed; disabled runs contained no router decisions. Small overlapping samples do not validate speed, cost, or the full benchmark. |

## A–D smoke comparison

Each row below is one fresh U02-equivalent task. Initial application snapshots,
prompt, parent model settings, and permissions matched. Elapsed time includes
the Codex task process and its server startup, not prepare/setup. Runs overlapped
on the shared machine. Total tokens are reported input plus output, including
cached input; they are not a monetary cost estimate.

| Variant | Seconds | Input | Cached input | Output | Required interventions |
| --- | ---: | ---: | ---: | ---: | ---: |
| A — Codex alone | 21.935 | 101,487 | 71,936 | 1,862 | 0 |
| B — fixed guidance | 27.150 | 157,174 | 128,384 | 2,142 | 0 |
| C — rules | 32.857 | 215,704 | 202,240 | 2,456 | 0 |
| D — rules + Qwen | 51.119 | 265,736 | 238,848 | 3,106 | 0 |

All four passed five independent application checks and ran their five updated
unit tests. D was slower and used more total tokens in this sample; this does
not support the proposed 10% improvement. Cache conditions, single samples, and
overlapping execution prohibit a general performance conclusion.

The U05 pair completed in 94.079s (A) and 67.202s (D). Their reported parent token
totals were 273,214 and 271,625, but **complete task usage is unknown** because
specialist usage is separate. Child rollouts can contain inherited parent
history; simply summing final totals would double-count. Reports flag this gap.
The two-project U06 report likewise marks primary-session usage incomplete;
it does not silently omit the second project's cost from a whole-task claim.

## Accounting and retained failures

Every driver attempt has its own ignored `.uat-runs/<run-id>/` with the original
prompt, configs, SQLite records, CLI and raw host events, router/tool events,
grader results, and intervention ledger. Read `report.json` for reviewed outcome;
`pilot-run.json` deliberately says `needs_evidence_review` until external review
and is not itself an acceptance decision. Developer tests/preflight probes are
not substituted for task attempts.

Run `python3 scripts/summarize_pilot.py` for the complete retained-attempt ledger,
including early missing-config, cancelled-tool, incomplete-preference, and
report-accuracy failures. Tester-side repairs/retries are conservatively recorded
as required interventions; initial prompts, setup, planned follow-ups, and the
browser inspection are separate. Failed and incomplete attempts remain in the
denominator. Successful final demonstrations do not erase earlier attempts.

At handoff, the complete development ledger contains **27 task attempts, 13
successful without required intervention (48.1%), and 10 required tester-side
interventions (0.37 per attempt)**. In the normal-operation subset, this is
12/21 (57.1%) and 9/21 interventions (0.43 per attempt). These are reviewed
scenario-level outcomes, not a claim that every eligible action was routed.
The full ledger also
includes deliberate preference changes, failure injection, and reporting tests;
these are not a randomized benchmark. Neither subset meets the PRD's 90% and
0.2 thresholds. Planned prompts/setup/inspection remain separately counted.

The >=90% zero-intervention success, <=0.2 mean interventions, no-increase versus
baseline, 99% repeatability, routing accuracy, and 40-task benchmark targets are
**not certified** by this development pilot.

## T01–T14 and remaining boundary

T01–T11 have code/protocol/inference coverage for loading/reuse, rules, actual
searches, failed observations, availability, precedence, validation, deadline,
invalid model output, and registry/preference boundaries. T12 has a five-repeat
real-model smoke, not the PRD's statistical consistency validation. T13 has real
autonomous correction plus explicit preference-change evidence; report fidelity
still needs work. T14 has independently graded real Codex bug fixes, but whole-
task quality and efficiency claims remain open.

Live U02/U03/U05/U09 against Linear and Notion are **blocked**: no designated
disposable Linear project ID or Notion page ID was supplied. `live-readiness`
returns a structured blocked result and performs no remote writes. Connectivity
to those specific targets and synthetic-content equivalence must be verified
before a live pass. No existing user projects/pages were seeded or changed.

Next work: improve eligible-routing adherence and honest omission reporting,
evaluate model choice quality on held-out goals, capture complete specialist
usage, then run an isolated repeated benchmark. Fine-tuning, RL, universal
discovery, and broad capability support remain outside this delivery.
