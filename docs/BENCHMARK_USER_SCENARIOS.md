# Five ground-truth user-test scenarios

Status: local fixtures, reference/milestone checks, CLI and paired-run integration
implemented. Five real default-model pairs ran at `dac1c61`, followed by five new
pairs at `631d8b9` after importing main's no-defer change (`8d60042`). Trace-accounting
gaps leave automatic acceptance unknown. The experiment report now presents the
latest observations and links the previous archive. Official upstream evaluator
integration remains pending.
Prepared 2026-09-18 on `feat/benchmark-user-scenarios`, from `main` at
`c8c59b074d47a1406d3a958137ea19a274319aea`.

Updated from `main` on 2026-09-18 by fast-forward to
`afab2bf2af6f6538d25c8d5994505324add451c6`
(`feat: add paired routing evaluation and model options`). At this sync, `main`,
`origin/main` and this branch point to that commit. Draft documentation was
preserved; no benchmark implementation or experiment was performed by this update.

Track scenario definitions, expected/observed behavior and every A/D attempt in
the [experiment report](BENCHMARK_EXPERIMENT_REPORT.md). The first B01–B05
observations are recorded there; do not pool them with unrelated pilot results.

## Implementation checkpoint — 2026-09-18

The runnable slice is documented in [benchmark commands and limits](../user_tests/BENCHMARKS.md).
It includes five exact public source prompts/tool catalogs, source/license hashes,
local SQLite tools, fresh paired worktrees, explicit `fixture_tool_use`, isolated
preferences, and reports that separate task calls from router recommendations.

This is deliberately labelled an **adapted local contract suite**, not completion
of every evaluator item in the original plan below. The official BFCL AST checker
and ToolSandbox runtime/scorer are not integrated yet. ToolSandbox currently uses
a reduced synthetic state, substring lookup and strict local final-text checks;
the full source milestone/ROUGE scores remain null. Preserve this distinction in
all results and review these disclosed adapters before making performance claims.

## Goal and boundaries

Create five understandable user tasks from actual BFCL and ToolSandbox entries,
then compare Codex alone with Codex + Rippletide using independently checkable
ground truth. This is a small benchmark-derived acceptance suite, not a leaderboard
submission, full benchmark, or proof of general performance.

Use the original user requests and tool descriptions first. Add only the disclosed
MCP transport, isolated state and measurement adapters. Do not initially translate
them into Linear tickets: that would introduce new task semantics and new oracles.
All tools operate on synthetic local state; no real shopping, SMS, account changes,
weather APIs, credentials or paid external services are needed for the fixtures.
Codex task inference still uses the configured Codex service.

The paired runner, routing hooks, model options and evidence reports are now
available on this branch through the imported main commit. Reuse those components;
do not build a second general-purpose runner. Do not modify the separate
`feat/routing-eval-models` worktree or reinstall the plugin during this planning task.

## Selected entries

| ID | User case, paraphrased | Exact upstream entry | Main ground truth |
| --- | --- | --- | --- |
| B01 | Retrieve past wind/temperature for coordinates, not a forecast or city lookup. | BFCL `multiple_5` | One specific function and its accepted coordinate/date arguments. |
| B02 | Find a bookstore selling a named book when only a shopping-cart tool exists. | BFCL `irrelevance_55` | No benchmark function call. |
| B03 | Retrieve Boston temperature/humidity and Rome precipitation for ten days. | BFCL `parallel_multiple_32` | Three specific calls with correct locations/horizon; order does not matter. |
| B04 | Find the user's next reminder relative to the current time. | ToolSandbox `search_reminder_with_recency_upcoming` | Clock lookup, dependent reminder query and expected reminder content. |
| B05 | Send a simulated message to a contact while cellular service starts disabled. | ToolSandbox `send_message_with_contact_content_cellular_off` | Prerequisite milestones, correct recipient/message state and completion response. |

Sources were inspected at immutable revisions:

- BFCL: `ShishirPatil/gorilla@6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`, `berkeley-function-call-leaderboard/bfcl_eval/data/` (V4 filenames).
- ToolSandbox: `apple-aiml-research/ToolSandbox@c8571d7854316d2e1c5f288e59fe1e34e53f6dd1`.

### B01 — Choose the correct historical lookup

Source: [request and three tool schemas][bfcl-multiple], [reference call][bfcl-multiple-answer].

- The original request identifies coordinates `(46.603354, 1.888334)` and 2019-12-13.
- Tools: `weather.get_by_city_date`, `weather.get_forecast_by_coordinates`,
  `weather.get_by_coordinates_date`.
- Required call: `weather.get_by_coordinates_date`, with those coordinates and
  `date="2019-12-13"`. Preserve upstream accepted values and type rules.
- User flow: submit the original request → choose a tool → execute against a
  local weather-data service → summarize the returned record.
- Implement real parameterized lookup over seeded historical and forecast rows.
  Wrong but valid calls should return their own data, not the expected answer.
- Grade function-name choice separately from the full upstream AST check. Seeded
  weather values and final-answer consistency are additional local checks, **not
  weather observations or answer ground truth supplied by BFCL**.

### B02 — Do not use an irrelevant tool

Source: [request/tool schema][bfcl-irrelevance], [upstream irrelevance evaluator][bfcl-relevance-checker].

- The user asks which bookstore sells *To Kill a Mockingbird*. The sole offered
  function is `add_product_to_cart(product_id, quantity, cart_id=0)`.
- Ground truth is the category's no-function-call rule, not a missing answer file:
  the upstream evaluator explicitly handles irrelevance without `possible_answer`.
- User flow: request availability information → recognize that the offered tool
  cannot retrieve it → explain the limitation without changing a cart.
- The cart tool must really work against an isolated synthetic cart if called.
  Never connect commerce credentials. A frozen cart snapshot provides an extra
  no-mutation safety assertion, separate from upstream scoring.
- Count a proposed cart call as a wrong tool choice even if a hook blocks it.
  A crash, missing transcript, or timeout is not successful abstention.
- An enabled run that correctly makes no task call but never consults Rippletide
  can pass the task check; router contribution is unobserved. Do not award a
  router-accuracy pass for absent evidence. Distinguish intentional model/rule
  abstention from a technical fallback that merely returns control to Codex.

Known risk, not a test result: [`router.py`](../plugins/rippletide/src/rippletide/router.py)
on this base returns `ONLY_CANDIDATE` before model inference. With the cart as the
single eligible candidate, that shortcut cannot establish relevance. Retain this
case and expose the behavior; do not add distractors, hide the cart, or hard-code
an exclusion just to make the case pass. Any later relevance fix is a separately
reviewed product change and must preserve before/after results.

### B03 — Complete all parts of a request

Source: [request/tool schemas][bfcl-parallel], [three reference calls][bfcl-parallel-answer],
[order-independent checker][bfcl-ast].

- `weather_forecast_temperature(location="Boston, USA", days=10)`.
- `weather_forecast_humidity(location="Boston, USA", days=10)`.
- `weather_forecast_precipitation(location="Rome, Italy", days=10)`.
- User flow: submit the combined request → identify all three needs → invoke the
  appropriate services → return all three results with correct location labels.
- Expose each function as a separate MCP tool, optionally on separate fixture
  servers to exercise cross-server routing. Preserve canonical upstream names in
  the adapter map. Each service queries its own seeded forecast data.
- Grade the call **multiset**, including argument values, omissions, duplicates
  and extra calls. Both sequential and concurrent execution can satisfy the
  upstream order-independent checker. Physical parallelism is not ground truth.
- Rippletide currently chooses one capability at a time: record every immediate
  decision and its actual invocation. Do not pass it the expected three choices
  or force Codex-alone into a serial schedule to hide routing overhead.

### B04 — Obtain prerequisite information before searching

Source: [scenario and milestones][ts-reminder], [base state][ts-base],
[default milestone ordering][ts-scenario].

- Tools: `get_current_timestamp`, `search_reminder`, `shift_timestamp`,
  `timestamp_to_datetime_info`; use the original scenario's allowlist.
- User flow: ask for the next reminder → obtain the fixture's time → search with
  a lower bound derived from that time → identify the seeded upcoming reminder.
- Preserve the upstream expected reminder record and content. Its grader checks
  the timestamp tool trace, the dependent search bound (one-second tolerance),
  and a final response containing the expected reminder text; prose similarity
  is also part of the upstream score.
- Clone one starting state for both arms and freeze the **fixture clock** during
  construction and execution. Do not independently regenerate relative dates for
  each arm or freeze the monotonic clock used to measure wall time.
- Preserve the milestone chain. Do not invent a unique full tool sequence for
  optional helper calls; expose milestone/argument correctness separately from
  extra-call counts. State must remain unchanged by this read-only task.

### B05 — Resolve prerequisites and verify the actual side effect

Source: [scenario, tools and milestone graph][ts-message], [local messaging implementation][ts-messaging].

- Tools: `search_contacts`, `get_cellular_service_status`,
  `set_cellular_service_status`, `send_message_with_phone_number`.
- Starting state: the original synthetic contact book with cellular service off.
- User flow: request the message → find the intended contact and enable simulated
  service → add the message to the local messaging database → confirm completion.
- Preserve the upstream contact, message content, recipient and milestone graph:
  contact lookup and enabling service may occur in either order; both precede
  the message-state milestone; confirmation follows it.
- Use upstream functions over their isolated execution context where feasible.
  The upstream send operation writes a local database and errors when cellular
  is off; it does not require a real SMS provider. Preserve those semantics.
- Report the original milestone/guardrail score, including its text-similarity
  components. Separately require exactly one newly sent message to the intended
  recipient, no unrelated contact/settings changes and no claimed success before
  execution. These stricter assertions are our local acceptance checks, not a
  replacement for or mislabeling of the upstream score.

## Original integration targets and remaining work

1. **Pin and extract only these five cases.** Store benchmark/revision/path/entry ID,
   source and oracle checksums, tool-name mapping, adapter version and applicable
   attribution/license notices. Keep the five-case selection fixed before results
   are known. Do not download a complete benchmark into the presented workspace.
2. **Build thin fixture adapters, not answer mocks.** BFCL needs local implementations
   because the selected entries supply schemas/reference calls, not the real weather
   data. ToolSandbox needs a separate locked environment if its dependencies conflict
   with the MCP runtime. Calls invoke approved functions, never arbitrary generated
   Python via `eval`/`exec`. Preserve `dict`/`tuple`/`float` semantics through explicit
   JSON-to-upstream type conversion and record every normalization.
3. **Add a narrow benchmark-fixture routing scope.** Current skills focus on searches,
   issue/requirements lookups and specialists. Generic weather/time helpers and
   synthetic writes must not be assumed covered. Propose an explicit fixture-only
   `fixture_tool_use` operation shared by each case's complete candidate set. Wire
   it through the fixture skill/profile and hook validation, including decisions
   to use no tool. Do not label mutation tools read-only or relax the normal remote
   MCP read-only policy. Permit writes only for allowlisted local fixture handlers
   in owned run state; reject remote URLs and arbitrary executables in that mode.
4. **Reuse paired execution and evidence contracts.** A/D get equal task text,
   tool schemas, model settings, initial state and permissions. Only D receives
   Rippletide instructions/router/hooks. No expected route preferences or oracle
   hints in either task. Keep the default RLCD model; other models are later reruns,
   not a prerequisite or a five-model matrix.
5. **Add deterministic grading and a compact report.** Translate observed external
   task calls back to upstream names for the pinned BFCL checker; pass ToolSandbox
   snapshots/traces to its pinned evaluator. Exclude router/control calls from the
   benchmark call set, while retaining their time/tokens in end-to-end metrics.
   Do not count internal helper invocations as additional agent choices.

Important implementation details:

- Oracle files, expected responses, grader code and ToolSandbox's hidden user-side
  instructions remain outside the agent-visible project, prompt and tools. Only
  agent-visible source messages are presented; hidden reminder answers must not leak.
- Route descriptions come from the source schemas, not the expected answer. Log
  the bounded context actually sent to Rippletide and any 1,024-token truncation or
  defer. A correct reference call does not prove the small model saw enough context.
- Pin effective preferences and record them; do not inherit a user's unrelated
  preferences or introduce case-specific rules that reveal the expected tool.
- Ground truth is authoritative for the dimensions it specifies. Do not use an
  LLM judge as the primary correctness oracle here. Additional prose/choice judgments
  are explicitly supplemental, never substituted for executable checks.
- A/D must operate on separate databases, server processes and run directories.
  Real tool results are captured, including errors. State snapshots and traces must
  be inaccessible through the tools except where the scenario explicitly permits.
- Both proposed and executed calls are recorded. A blocked bad proposal, a failed
  invocation, a correct recommendation with no execution, and an unrouted success
  are different outcomes.

## User flow and small run budget

1. User chooses B01–B05 or the five-case set; no task writing or ground-truth editing.
2. Setup validates source hashes, fixture tools, grading and plugin readiness outside
   the measured task. No task agent sees or consumes the golden trajectory.
3. Create fresh A/D projects and state, submit the same original request in fresh
   sessions, and run both arms in parallel if requested.
4. Run the external checkers, retain raw evidence and show a side-by-side report.
5. Open a failure's decision/call/state trace without manually reconstructing it.

First smoke: one pair per case = **10 task attempts**. Once the harness is sound,
extend to **three pairs per case = 30 total attempts**, including valid smoke
attempts only if their configuration is identical. Keep abandoned/failed attempts
in the record; never replace failures silently. Initial thresholds and cases are
frozen before measurement, and observed case data is not used for fine-tuning.

Parallel execution meets the requested workflow, but shares hardware and service
limits. Label it accordingly. For cleaner latency comparisons, use sequential
pairs with alternating arm order. That costs elapsed experiment time but reduces
resource contention; it is not a different correctness test. Avoid optional
specialists in these cases: they add cost without benchmark-defined agent-choice
ground truth. Existing U04/U05 cover real specialist behavior separately.

## Report and success criteria

| Measure | Definition / evidence |
| --- | --- |
| Upstream case score | Pinned BFCL checker result or ToolSandbox milestone/guardrail score; do not invent a binary threshold for a graded similarity score. |
| Tool-choice correctness | BFCL expected function or call multiset; ToolSandbox trace/milestone constraints only where specified. Other next choices can be ungraded rather than declared wrong. |
| Argument correctness | Accepted values/types or dependent-value constraints, scored separately from selecting the tool. |
| Local task acceptance | Seeded result consistency, required final state and explicitly listed extra safety checks. |
| Routing contribution/compliance | Rule/model/fallback source, registered proposed calls, linked decisions/executions, omissions, blocks and unverified matches. |
| Time | Task wall time and per-route latency; setup, cold load and grading reported separately. All route/tool retries remain in task time. |
| Tokens | Full Codex task input/cached-input/output usage, including any actual children; local router input/readout counts separately. Missing usage is incomplete, not zero. |
| Cost | No “cheaper” claim from raw tokens alone. Report model and usage categories; any later price estimate must disclose its rates and include all relevant work. |
| Human intervention | Required corrections and total interactions separately; planned initial prompts/setup do not count as corrections. Successful runs without intervention / all attempted runs. |
| Repeatability | Per-case outcomes and acceptable tool choices across identical repeats. Do not penalize legitimate unordered calls or claim determinism from three runs. |

Suite readiness means: every grader accepts a golden trace and rejects relevant
wrong-tool, wrong-argument, missing-step and incorrect-state traces; both arms use
identical snapshots; isolation and telemetry are verified; every attempted task
has a retained result or an explicit missing-evidence status. Also test B02 with
a blocked cart attempt and B03 with reordered, duplicated and omitted calls.

Product evidence is separate: report each case's success and zero-intervention
completion, accuracy and paired time/token differences without averaging away a
correctness regression. Faster/cheaper claims require comparable successful
results and complete measurements. The existing PRD's ≥90% no-intervention
completion and ≤0.2 required interventions per task remain targets, not validated
claims from five hand-selected cases. A failed product case can still demonstrate
that the test harness works correctly.

## Planned delivery slices

| Order | Deliverable | Verification before moving on | Status |
| --- | --- | --- | --- |
| 0 | Scenario plan and human-readable experiment tracker | All five entries identify the user need, tools, expected behavior and separate A/D observations; no fabricated results. | Documented; first five pairs now recorded. |
| 1 | Pinned source manifest and B01/B02 fixture tools/graders | Golden calls pass; wrong tool/arguments fail; B02 cart attempt fails and unchanged state is checked; no network or oracle leakage. | Implemented and locally tested. Local reference-call checker; official AST integration pending. |
| 2 | B03 multi-call fixtures and grading | Reordered correct calls pass; omitted, extra, duplicate or mis-parameterized calls fail; every observed call is retained. | Implemented and locally tested with local reference-call grading. |
| 3 | B04/B05 ToolSandbox adapter, fixed time and isolated state | Golden milestone trajectories pass; broken prerequisites, wrong records/recipients and unsafe extra changes are reported; cloned clocks/state match. | Local deterministic adapters tested; original runtime, full seed state and official evaluator pending. |
| 4 | Extend the imported paired runner with fixture-only routing and benchmark grading | Both arms have equivalent tools; local synthetic writes are allowed without relaxing remote policy; decision receipts, no-call outcomes and complete metrics are verified. | Fresh installed-host tests ran; catalog-discovery and failed-call trace accounting need correction before acceptance can be certified. |
| 5 | First five paired experiments and report updates | Ten task attempts have independent results, traces, time/tokens/coverage and intervention ledgers; failed and blocked outcomes remain visible. | Five pairs at `dac1c61` plus five rerun pairs at `631d8b9`; automatic grades unknown, metrics and observed behaviors retained in current/archived reports. |
| 6 | Repeatability and performance follow-up | Up to three comparable pairs per case; versioned report explains differences without claiming full-benchmark validation. | After smoke/harness review. |

Concrete integration points verified at `afab2bf`:

- [`profiles.py`](../user_tests/src/rippletide_uat/profiles.py) and
  [`paired.py`](../user_tests/src/rippletide_uat/paired.py) already supply approved
  tool profiles, paired execution and `independent_checks`. Extend them for
  benchmark state/clock snapshots and external pinned graders; preserve existing
  project-test behavior.
- The profile, routing skill and [`guard.py`](../plugins/rippletide/scripts/guard.py)
  currently recognize three operation families. The runner rejects mutation-labelled
  MCP tools. B02/B05 therefore need the explicit local-fixture scope and write
  exception described above, not false read-only annotations or a global bypass.
- [`cli.py`](../user_tests/src/rippletide_uat/cli.py) already supports `--no-judge`.
  Use executable benchmark checkers by default for these cases, without spending
  an extra model turn on grading. The proposed benchmark command should reuse the
  existing runner and expose parallel/sequential experiment mode explicitly.
- [`paired_evidence.py`](../user_tests/src/rippletide_uat/paired_evidence.py) already
  reads evidence-backed `fixture-approved` records from `fixture-grades.jsonl` and
  produces private evidence plus share-safe reports. Add case-level results for
  abstention, call-multiset completeness and final state: a per-call record alone
  cannot grade B02's correct absence of calls or B03's missing calls. Bind every
  grade to the source/oracle version and observed trace; never manufacture a call
  solely to attach a grade. Follow the existing [evidence contract](../user_tests/PAIRED_EVIDENCE.md).

Implemented user command (requires this branch's installed plugin and pinned host):
`rippletide-uat benchmark run --cases B01 B02 B03 B04 B05 --repeat 1`.
The output links to per-pair evidence and a generated experiment report. The
tracked human report is updated after review; the CLI does not silently modify
source documentation. It remains a summary, not a substitute for retained raw data.

Out of scope: full benchmark downloads/runs, leaderboard claims, new live providers,
RL/fine-tuning, universal routing, fabricated agent-selection labels, and modifying
the separate implementation worktree.

[bfcl-multiple]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_multiple.json#L6
[bfcl-multiple-answer]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/possible_answer/BFCL_v4_multiple.json#L6
[bfcl-irrelevance]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_irrelevance.json#L56
[bfcl-relevance-checker]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/eval_checker/eval_runner.py#L263
[bfcl-parallel]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_parallel_multiple.json#L33
[bfcl-parallel-answer]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/possible_answer/BFCL_v4_parallel_multiple.json#L33
[bfcl-ast]: https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/eval_checker/ast_eval/ast_checker.py#L554
[ts-reminder]: https://github.com/apple-aiml-research/ToolSandbox/blob/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1/tool_sandbox/scenarios/multiple_tool_call_scenarios.py#L4083
[ts-message]: https://github.com/apple-aiml-research/ToolSandbox/blob/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1/tool_sandbox/scenarios/multiple_tool_call_scenarios.py#L1356
[ts-base]: https://github.com/apple-aiml-research/ToolSandbox/blob/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1/tool_sandbox/scenarios/base_scenarios.py
[ts-scenario]: https://github.com/apple-aiml-research/ToolSandbox/blob/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1/tool_sandbox/common/scenario.py#L232
[ts-messaging]: https://github.com/apple-aiml-research/ToolSandbox/blob/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1/tool_sandbox/tools/messaging.py#L39
