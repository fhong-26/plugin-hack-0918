# Benchmark-derived user tests — experiment tracker

Last updated: 2026-09-18. Status: **local harness implemented; no real B01–B05 Codex experiments run**.
This is the human-readable record of what each user needs, what should happen,
and what native Codex and Codex + Rippletide actually do. Implementation details
and pinned source links are in the [scenario plan](BENCHMARK_USER_SCENARIOS.md).

Current product base: `afab2bf2af6f6538d25c8d5994505324add451c6`, imported from
`main` into `feat/benchmark-user-scenarios` on 2026-09-18. Its paired runner and
evidence tooling are available. This branch now adds five local adapted fixtures,
deterministic reference/milestone graders and paired-run integration. Official
upstream evaluators remain pending. Historical pilot reports imported with that
commit are not B01–B05 observations.

## Experiment question

For five tasks with externally defined ground truth, does Rippletide preserve
correct tool use and task outcomes while reducing time, tokens or required human
help compared with native Codex?

"Native Codex" means Codex without the Rippletide plugin, but with the **same task
tools**, model/settings, starting data and permissions as the enabled arm. It
does not mean an agent with no MCP tools. The enabled arm lets Rippletide choose
registered capabilities; Codex still constructs arguments and executes them.

Expected behavior below is a specification, **not an observed result**. Use
`Not run`, `Unknown`, `Incomplete`, `Passed`, `Failed`, `Blocked` or `Timed out`
accurately. A blank result must never become zero tokens or zero interventions.
Other project pilots are not results for these benchmark entries.

## Current status

| Case | User need | Ground truth | Fixture/grader ready | Native Codex | Codex + Rippletide | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| B01 | Historical weather at coordinates/date | BFCL `multiple_5`: function + arguments | Local adapter/checks tested | Not run | Not run | No agent-run evidence |
| B02 | Find a bookstore, not purchase a book | BFCL `irrelevance_55`: no function call | Local adapter/checks tested | Not run | Not run | No agent-run evidence |
| B03 | Three forecast results across two cities | BFCL `parallel_multiple_32`: call multiset + arguments | Local adapter/checks tested | Not run | Not run | No agent-run evidence |
| B04 | Identify the next reminder | ToolSandbox `search_reminder_with_recency_upcoming`: dependent traces + response | Adapted local checks tested; official scorer pending | Not run | Not run | No agent-run evidence |
| B05 | Send one simulated message despite a disabled service | ToolSandbox `send_message_with_contact_content_cellular_off`: milestone graph + state | Adapted local checks tested; official scorer pending | Not run | Not run | No agent-run evidence |

Planned smoke size: **five pairs / ten task attempts**. Actual benchmark attempts:
**none**. This tracker makes no current claim about relative performance.

### Harness verification is not a product experiment

The [implementation guide](../user_tests/BENCHMARKS.md) explains commands and exact
grading limits. Automated tests execute all five fixtures through real STDIO MCP,
accept golden local trajectories and reject wrong choices/arguments, omitted or
duplicate calls, invalid prerequisites and state changes. They also cover source
provenance, isolated state, remote-write rejection and missing-evidence handling.
Synthetic host transcripts exercise report correlation, not actual Codex behavior.

The first slice does **not** run the official BFCL AST or ToolSandbox evaluators:
upstream scores remain null. Reduced synthetic ToolSandbox data, substring search,
fixed UTC time and stricter local final-text checks are disclosed adaptations.
Weather values are fixture data, not BFCL-provided observations. Before a real
comparison, install this branch's plugin and validate readiness in fresh sessions.
The personal plugin installation was not changed during this implementation.

Verified locally on 2026-09-18:

| Check | Observed result |
| --- | --- |
| Test-kit suite, including 44 benchmark tests | 150 passed |
| Plugin runtime/guard suite | 69 passed; 13 opt-in model checks skipped |
| Repository unittest suite | 17 passed; 2 optional checks skipped |
| Pinned-source re-extraction | All five cases / 17 source-file hashes match |
| Plugin and routing-skill validators | Passed |

These counts establish harness/code checks only. They contribute **zero** task
attempts to the native-Codex/Rippletide experiment denominator.

## B01 — Historical weather, not a forecast

**User need.** Retrieve wind speed and temperature for coordinates
`(46.603354, 1.888334)` on 2019-12-13.

| Possible tool | Purpose | Appropriate here? |
| --- | --- | --- |
| `weather.get_by_city_date` | Historical weather using a city name | Not the reference choice; the user supplied coordinates. |
| `weather.get_forecast_by_coordinates` | Future weather using coordinates | No; the request concerns a past date. |
| `weather.get_by_coordinates_date` | Historical weather using coordinates/date | Yes; the benchmark reference function. |

**Right behavior.** Call `weather.get_by_coordinates_date` with the supplied
coordinates and `date="2019-12-13"`, then accurately relay the seeded result.
The upstream checker grades the call; our fixture checks final-answer consistency.
BFCL does not supply actual historical weather measurements for this case.

| Comparison | Native Codex | Codex + Rippletide |
| --- | --- | --- |
| Expected decision flow | Select the historical-coordinate function, supply arguments and call it. | Send the immediate goal to Rippletide, receive a selection, then supply arguments and execute the matching function. |
| Observed selected/proposed tool | Not run | Not run |
| Observed executed call and result | Not run | Not run |
| Tool-choice / argument / task checks | Not run | Not run |
| Time / token usage / human interventions | Not run | Not run |

**Investigate when run:** wrong historical-vs-forecast selection, coordinate/date
mistakes, router selection differing from execution, or extra calls that increase
cost without improving the answer. Do not attribute argument mistakes to the
small model automatically.

## B02 — Recognize that the available tool cannot help

**User need.** Find an online bookstore selling *To Kill a Mockingbird*. The user
has not asked to add anything to a cart.

| Possible tool | Purpose | Appropriate here? |
| --- | --- | --- |
| `add_product_to_cart` | Add an identified product/quantity to a synthetic cart | No; it does not search bookstore availability. |

**Right behavior.** Make no benchmark task-tool call and explain the capability
limitation. Keep the synthetic cart unchanged. Rippletide's route/status calls
are control calls, not benchmark task calls. A proposed cart call is a wrong tool
choice even if a guard prevents its execution; blocked execution is a separate
safety outcome. A crash or silent timeout is not correct abstention.

| Comparison | Native Codex | Codex + Rippletide |
| --- | --- | --- |
| Expected decision flow | Recognize irrelevance; do not call the cart tool. | Consult the router; it should not select the irrelevant cart tool. Codex then gives an honest limitation response. |
| Observed task-tool proposals/calls | Not run | Not run |
| Observed final response / cart state | Not run | Not run |
| No-call / no-mutation checks | Not run | Not run |
| Time / token usage / human interventions | Not run | Not run |

**Known hypothesis, not a measurement.** At the current main commit, the
`ONLY_CANDIDATE` shortcut selects the sole eligible route without relevance
inference. This may fail this scenario. Do not remove the case or insert an
answer-revealing exclusion. Record rule/model/fallback source. If the enabled
agent succeeds without consulting Rippletide, task success can pass but router
contribution remains unverified. A technical fallback is not proof of learned
or intentional abstention.

## B03 — Fulfil every part of a combined request

**User need.** Get ten-day temperature and humidity forecasts for Boston, USA,
plus ten-day precipitation for Rome, Italy.

| Possible tool | Required arguments |
| --- | --- |
| `weather_forecast_temperature` | `location="Boston, USA", days=10` |
| `weather_forecast_humidity` | `location="Boston, USA", days=10` |
| `weather_forecast_precipitation` | `location="Rome, Italy", days=10` |

**Right behavior.** Make all three required calls and return correctly labelled
results. The upstream checker is order-independent: serial and concurrent calls
can both be correct. Missing, extra or duplicated calls are not silently removed
before grading. Seeded forecast values are our local fixture data.

| Comparison | Native Codex | Codex + Rippletide |
| --- | --- | --- |
| Expected decision flow | Identify all three needs and execute their functions in any valid order. | Route each immediate need, then execute the corresponding functions; retain a decision-to-call link for each. |
| Observed call sequence/multiset | Not run | Not run |
| Observed omissions / duplicates / extra calls | Not run | Not run |
| Tool-choice / argument / completeness checks | Not run | Not run |
| Time / token usage / human interventions | Not run | Not run |

**Investigate when run:** missing subtasks, swapping cities, repeated routing,
and serialization overhead. Do not constrain native Codex to a slower schedule
to make the enabled version appear faster. Separate tool-call parallelism from
running the two experimental arms in parallel.

## B04 — Resolve “upcoming” using the current time

**User need.** Identify the user's next reminder rather than an old reminder.

| Possible tool | Purpose |
| --- | --- |
| `get_current_timestamp` | Read the synthetic environment's current time. |
| `search_reminder` | Retrieve reminders using temporal and other filters. |
| `shift_timestamp` | Calculate a timestamp offset when needed. |
| `timestamp_to_datetime_info` | Convert a timestamp to date/time information. |

**Right behavior.** Obtain time, use it as the required reminder-search lower
bound, and return the upcoming reminder's content. Preserve the upstream
one-second bound tolerance and expected content. Optional helper tools do not
have an invented single correct next-action label. The fixture clock is frozen
and identical between arms; measurement clocks still run normally.

| Comparison | Native Codex | Codex + Rippletide |
| --- | --- | --- |
| Expected decision flow | Obtain the prerequisite time and then perform the dependent query. | Route the time lookup, feed its compact observed result into the subsequent decision, then query and answer. |
| Observed prerequisite/query sequence | Not run | Not run |
| Observed time / filter bound / returned record | Not run | Not run |
| Upstream milestone score / local read-only checks | Not run | Not run |
| Time / token usage / human interventions | Not run | Not run |

**Investigate when run:** guessed time, selection based on stale context, missing
observations, an incorrect bound or a past reminder returned as upcoming. Preserve
the upstream text-similarity score separately from deterministic trace checks.
The hidden expected answer must never enter the task prompt or router context.

## B05 — Complete a simulated message workflow with prerequisites

**User need.** Send the specified message to the named fixture contact, with
cellular service initially disabled. No real person or device is contacted.

| Possible tool | Purpose |
| --- | --- |
| `search_contacts` | Resolve the named synthetic contact and phone number. |
| `get_cellular_service_status` | Inspect simulated service availability. |
| `set_cellular_service_status` | Change simulated service state only. |
| `send_message_with_phone_number` | Append a message to the local messaging state. |

**Right behavior.** Resolve the contact and enable service, in either order;
then successfully send the message and confirm completion. Match the original
recipient/content and milestone graph. The upstream send operation must reject
execution while service is off. An observed failed early attempt is a separate
execution failure; assess the complete trajectory with the upstream grader
rather than inventing a stricter hidden tool-order rule.

| Comparison | Native Codex | Codex + Rippletide |
| --- | --- | --- |
| Expected decision flow | Discover/resolve prerequisites, execute the allowed local state change, then confirm. | Route bounded choices using available observations; Codex constructs arguments and executes prerequisites and the final send. |
| Observed contact/settings/send sequence | Not run | Not run |
| Observed message / recipient / before-and-after state | Not run | Not run |
| Upstream milestone score / extra safety checks | Not run | Not run |
| Time / token usage / human interventions | Not run | Not run |

**Investigate when run:** invented phone numbers, repeated sends, missing service
enablement, unrelated state changes, premature success claims and whether one
version needs human help. Our extra acceptance checks require one new message
and no unrelated changes; label these as local checks, not upstream ground truth.

## Run ledger — append one entry per actual pair

No runs recorded. Do not fill this ledger with another fixture's or a Koesio
pilot's measurements. Planned slots are not attempted experiments.

For every new pair, retain these fields in the machine-readable manifest and
append a concise summary here:

| Record | Required contents |
| --- | --- |
| Identity | Pair/run IDs, B01–B05 entry, date, repetition and attempt number; source/grader/adapter hashes. |
| Configuration | Product commit plus dirty-patch hash if applicable, Codex version/resolved model/effort, router engine and weights revisions, registry/preferences, clock/seed, tool catalog, concurrency mode. |
| Comparability | Matching prompts, allowed tools, permissions and initial-state hashes; disclosed differences and invalid-comparison reasons. |
| Native Codex observations | Proposed tools, actual calls/arguments, results, retries, final response and state. |
| Rippletide observations | Immediate Codex request → bounded context → returned choice/source/reason → proposed/actual call; decision IDs and invocation IDs, omissions and blocks. |
| Correctness | Upstream result/score, choice check, argument check, execution outcome, local acceptance, routing compliance; unsupported judgments marked unknown. |
| Metrics | Task seconds; input/cached-input/output tokens and coverage; small-model tokens/readouts and latency separately; required interventions and total interactions separately. |
| Evidence | Private traces, grader outputs, state snapshots, machine-readable results and share-safe report links. |
| Interpretation | What differed, evidence-backed explanation, limitations and next experiment. A causal hypothesis must be labelled as such. |

Observable requests, returned explanations and actual calls are the evidence.
Do not invent native Codex's internal reasoning. Router/control overhead and all
retries belong in end-to-end metrics. Setup, cold startup and grading costs remain
visible but separate. For these cases, ground-truth checkers replace the optional
LLM judge as the primary oracle; if a supplemental judge is used, account for it
separately and label its output provisional.

### Per-pair result template

Copy this table beneath a real pair ID only after an attempt starts. `Unknown`
means missing evidence, not failure or zero. Keep failed/timed-out attempts.

| Metric | Native Codex | Codex + Rippletide | Difference / interpretation |
| --- | --- | --- | --- |
| Attempt status | Unknown | Unknown | Pending evidence |
| Upstream score/result | Unknown | Unknown | Pending evidence |
| Tool-choice correctness / coverage | Unknown | Unknown | Pending evidence |
| Router recommendation correctness | Not applicable | Unknown | Can be wrong even when Codex declines the recommendation and completes correctly. |
| Argument correctness | Unknown | Unknown | Pending evidence |
| Task acceptance | Unknown | Unknown | Pending evidence |
| Routing compliance / contribution | Not applicable | Unknown | Do not equate task success with routed success. |
| Task seconds | Unknown | Unknown | Compute enabled minus baseline only for comparable runs. |
| Input / cached-input / output tokens | Unknown | Unknown | Show categories; cached input is not extra input. |
| Small-model latency / token readouts | Not applicable | Unknown | Separate from Codex token totals. |
| Required interventions / total interactions | Unknown | Unknown | Initial planned prompts are not corrective interventions. |
| Evidence links | None | None | No result is verified without evidence. |

## Conclusions and update discipline

Current conclusion: **no performance or correctness conclusion yet**.

- Start with one pair per case; expand to three repetitions only after the
  harness/grader checks pass. Parallel runs are useful for the user flow;
  sequential alternating order is preferable for cleaner time comparisons.
- Compare efficiency alongside correctness. Preserve raw timings for failures,
  but do not call a fast unsuccessful run a speed improvement. Never infer a
  monetary saving from undifferentiated token counts.
- Keep every attempt in the outcome denominator. Report setup-blocked pairs
  separately from started task attempts; missing data must remain visible.
- Append attempts and corrections with timestamps; do not overwrite unfavorable
  results. If a product/adapter/grader changes, record a new versioned experiment
  and retain the old results. Do not pool incompatible configurations.
- Expected behavior and oracle changes require an explicit versioned rationale;
  do not rewrite them after seeing a model's answer to make it pass.
- Report repeated valid choices and outcomes; five selected cases and three
  repetitions cannot establish general accuracy, speed, savings or determinism.

## Change log

| Date | Update | Evidence/status |
| --- | --- | --- |
| 2026-09-18 | Created the five-case experiment tracker and comparison templates. | Planning only; zero benchmark task attempts. |
| 2026-09-18 | Fast-forwarded this branch to the new main commit and preserved the draft documents. | `main`, `origin/main` and branch HEAD at `afab2bf2af6f6538d25c8d5994505324add451c6`; paired runner/model options imported. No benchmark attempts. |
| 2026-09-18 | Implemented five local fixture adapters, source extraction, local graders, fixture-only routing, paired CLI and evidence reporting. | Developer verification only; official-scorer integration and actual Codex comparisons pending. No speed, cost or determinism claim. |
