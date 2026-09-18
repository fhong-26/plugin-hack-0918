# Benchmark-derived user tests — experiment tracker

Last updated: 2026-09-18. Status: **five real pairs run; ten task processes completed; automatic acceptance remains unknown because of trace-accounting gaps**.
This is the human-readable record of what each user needs, what should happen,
and what native Codex and Codex + Rippletide actually do. Implementation details
and pinned source links are in the [scenario plan](BENCHMARK_USER_SCENARIOS.md).

Tested implementation: `dac1c61c7547f10fda38b3fb30747a3b9701e1a4` on
`feat/benchmark-user-scenarios`, with a clean source tree for every pair. Personal
plugin build `0.1.0+codex.20260918135952` was installed using the plugin-creator
cachebuster/reinstall workflow and its source was verified in fresh private
sessions. Previous installation copies were preserved. The implementation is
based on `afab2bf`; historical pilots are not included in these observations.

The [machine-readable snapshot](results/benchmark-smoke-2026-09-18.json) retains
run IDs, source/runtime/grader hashes, settings, token categories, decisions,
observed calls, final answers and state observations. Raw logs/databases remain
outside Git. Official BFCL/ToolSandbox evaluators were **not** run.

## Experiment question

For five tasks with externally defined ground truth, does Rippletide preserve
correct tool use and task outcomes while reducing time, tokens or required human
help compared with native Codex?

"Native Codex" means Codex without the Rippletide plugin, but with the **same task
tools**, model/settings, starting data and permissions as the enabled arm. It
does not mean an agent with no MCP tools. The enabled arm lets Rippletide choose
registered capabilities; Codex still constructs arguments and executes them.

Expected behavior below is a specification; observed rows are explicitly marked. Use
`Not run`, `Unknown`, `Incomplete`, `Passed`, `Failed`, `Blocked` or `Timed out`
accurately. A blank result must never become zero tokens or zero interventions.
Other project pilots are not results for these benchmark entries.

## Current status

| Case | User need | Ground truth | Fixture/grader ready | Native Codex | Codex + Rippletide | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| B01 | Historical weather at coordinates/date | BFCL `multiple_5`: function + arguments | Local adapter/checks tested | Correct historical call observed | Wrong forecast call, then correct historical call | Automatic grades unknown; raw calls show the extra wrong choice |
| B02 | Find a bookstore, not purchase a book | BFCL `irrelevance_55`: no function call | Local adapter/checks tested | No cart call; limitation explained | Wrong rule recommendation declined by Codex; no cart call | Automatic grades unknown; unchanged state observed |
| B03 | Three forecast results across two cities | BFCL `parallel_multiple_32`: call multiset + arguments | Local adapter/checks tested | All three required calls observed | All three Qwen-selected calls observed | Automatic grades unknown; correct arguments visible |
| B04 | Identify the next reminder | ToolSandbox `search_reminder_with_recency_upcoming`: dependent traces + response | Local checks tested; official scorer pending | Time → filtered search → correct reminder | No clock call; lower bound 0; past reminder returned | Automatic grades unknown; explicit incorrect behavior observed |
| B05 | Send one simulated message despite a disabled service | ToolSandbox `send_message_with_contact_content_cellular_off`: milestone graph + state | Local checks tested; official scorer pending | Recovered from service-off error; one message sent | Recovered from service-off error; one message sent | Automatic grades unknown; fixture state and calls inspected |

Actual smoke size: **five pairs / ten started tasks**, one repetition per case,
zero setup-blocked or timed-out pairs. No attempts were discarded. Prepared-only
CLI checks from before this experiment are not counted as user attempts.

### Default settings and comparability

Command: `uv run --locked --project user_tests rippletide-uat benchmark run --cases B01 B02 B03 B04 B05`.

- Codex CLI `0.155.0`; model and effort were not supplied. Both arms resolved to
  `gpt-6-astra` in all five pairs. Effort was not emitted explicitly; it is not
  assumed to be a particular level.
- Rippletide used default `qwen25-rlcd`, the pinned RLCD engine and its pinned
  Qwen2.5-1.5B MLX weights, with allowed-token argmax and no sampling.
- Each pair ran concurrently on the same Mac; cases ran sequentially. Starting
  state, public task, available task tools and permissions matched within pairs.
- No corrective human inputs or optional model-judge calls were made. The
  initial planned prompt is counted separately from interventions.

### Measured task metrics

Times are task-process wall seconds, not isolated model latency. Tokens below
are **Codex input + output**, including routing turns in the enabled arm. Cached
input is already part of input and is not added again. Coverage was complete
for all ten recorded task token totals despite the separate tool-trace gap.

| Case | Native seconds | Rippletide seconds | Native total tokens | Rippletide total tokens | Required interventions, native / enabled |
| --- | ---: | ---: | ---: | ---: | --- |
| B01 | 7.931 | 19.557 | 35,949 | 81,443 | 0 / 0 |
| B02 | 5.850 | 13.460 | 23,358 | 37,109 | 0 / 0 |
| B03 | 15.726 | 18.644 | 36,338 | 82,723 | 0 / 0 |
| B04 | 8.443 | 22.566 | 49,991 | 88,523 | 0 / 0 |
| B05 | 22.127 | 34.881 | 75,201 | 171,593 | 0 / 0 |
| Sum of task measurements | 60.077 | 109.108 | 220,837 | 461,391 | 0 / 0 |

Observed aggregate task time was **1.82×** and total Codex tokens **2.09×** the
baseline. Rippletide was slower and used more tokens in each of the five pairs.
These are descriptive measurements, not a causal/general performance estimate.
The time sum is not the elapsed duration of the parallel suite.

| Accounting category, all five cases | Native | Rippletide |
| --- | ---: | ---: |
| Task input tokens | 219,831 | 458,602 |
| Of which cached input | 157,354 | 380,260 |
| Task non-cached input, by subtraction | 62,477 | 78,342 |
| Task output tokens | 1,006 | 2,789 |
| Setup/preflight tokens, separate from tasks | 352,910 | 456,246 |
| Setup/preflight wall seconds, summed | 97.747 | 86.123 |
| Planned task prompts | 5 | 5 |
| Required corrective interventions | 0 | 0 |

The enabled arm recorded 13 model decisions and one `ONLY_CANDIDATE` rule
decision, with no technical fallbacks. Their total recorded routing latency was
1.424 seconds; small-model usage was 1,746 input tokens and 13 label readouts
(zero autoregressively generated output tokens). Cold worker startup observed
during preflight ranged from 3.39 to 3.81 seconds. These local-model readouts and
setup tokens are separate from the Codex task token totals. No monetary cost
estimate or saving is claimed.

### Why automatic correctness remains unknown

Every session used a `functions.exec` container solely to inspect `ALL_TOOLS`.
The conservative grader expects a nested tool hook for every such container;
pure catalog inspection has none, so `unobserved_host_containers=1` invalidates
trace completeness in every arm. Inspection of the recorded discovery snippets
shows catalog filtering only; this observation does **not** override the frozen
automatic grades.

B05 has another gap: each service-off send error is in the fixture database,
but has no matching `tool_completed` hook. There are four fixture events and
only three fixture completion hooks per arm. Do not treat the missing failure
hook as a successful call or discard the failed attempt.

Therefore the suite command exited **1**, not success. All ten local automatic
grades and their verified-model-execution counts remain unknown/null. Explicit
wrong calls and answers can still be described from the evidence; absence of a
certified passing grade is not proof every task failed. We publish no certified
pass rate and no official benchmark score. Grader/oracle code was not changed
after observing these answers.

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
Weather values are fixture data, not BFCL-provided observations. This experiment
installed the branch's plugin and passed fresh-session readiness checks before
each measured pair.

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
| Observed selected/proposed tool | Historical-coordinate tool immediately | Qwen first chose coordinate forecast, then historical-coordinate tool |
| Observed executed call and result | One historical call; 7.25°C and 18.5 km/h returned | Both selected tools executed; final response contained correct historical values |
| Tool-choice / argument / task checks | Reference tool/date/coordinates observed; automatic grade unknown | Extra forecast violates exact call multiset; final answer recovered; automatic grade unknown |
| Time / total tokens / required interventions | 7.931 s / 35,949 / 0 | 19.557 s / 81,443 / 0 |

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
| Observed task-tool proposals/calls | None | None; Codex declined the cart recommendation |
| Observed final response / cart state | Explained tool limitation; state unchanged | Explained tool limitation; state unchanged |
| No-call / no-mutation checks | Supported by observed trace/state; automatic grade unknown | Same, but router recommendation was incorrect; automatic grade unknown |
| Time / total tokens / required interventions | 5.850 s / 23,358 / 0 | 13.460 s / 37,109 / 0 |

**Observed rule failure.** `ONLY_CANDIDATE` selected `add_product_to_cart` without
model inference. Codex consulted Rippletide but did not execute that inappropriate
recommendation. The favorable no-call outcome is not evidence of Qwen choosing
to abstain. No answer-revealing exclusion or product fix was added during the run.

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
| Observed call sequence/multiset | All three calls issued together with `Promise.allSettled` | Temperature → humidity → precipitation, each after its Qwen selection |
| Observed omissions / duplicates / extra calls | None in fixture records | None in fixture records |
| Tool-choice / argument / completeness checks | Reference city/day arguments and labelled results observed; automatic grade unknown | Same; all three router function-membership grades correct; automatic task grade unknown |
| Time / total tokens / required interventions | 15.726 s / 36,338 / 0 | 18.644 s / 82,723 / 0 |

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
| Observed prerequisite/query sequence | `get_current_timestamp` → `search_reminder` | `search_reminder` only; Qwen selected search, shift, then search across three requests |
| Observed time / filter bound / returned record | Clock 1778846400; equal lower bound; correct bathing-dress reminder | Bound 0; no current-time lookup; final answer named the old library-book reminder with an uncertainty caveat |
| Upstream milestone score / local read-only checks | Official score not run; unchanged state; automatic local grade unknown | Official score not run; unchanged state but required dependency and answer missing; automatic local grade unknown |
| Time / total tokens / required interventions | 8.443 s / 49,991 / 0 | 22.566 s / 88,523 / 0 |

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
| Observed contact/settings/send sequence | Contact lookup → failed send (service off) → enable service → successful send | Same executed sequence; initial Qwen send recommendation was first declined because phone number was unknown |
| Observed message / recipient / before-and-after state | One new message to +12453344098 with requested text; only cellular/messages changed | Same; five model decisions for four executed calls, including the failed send |
| Upstream milestone score / extra safety checks | Official score not run; successful send followed prerequisites; automatic local grade unknown | Same; no extra message or unrelated state change observed; automatic local grade unknown |
| Time / total tokens / required interventions | 22.127 s / 75,201 / 0 | 34.881 s / 171,593 / 0 |

**Investigate when run:** invented phone numbers, repeated sends, missing service
enablement, unrelated state changes, premature success claims and whether one
version needs human help. Our extra acceptance checks require one new message
and no unrelated changes; label these as local checks, not upstream ground truth.

## Run ledger — append one entry per actual pair

All pairs below used implementation `dac1c61`, default models and parallel arms
on 2026-09-18. The links open the presentation HTML; each directory also contains
`report.md`, `report.json`, `benchmark-report.md`, private raw/normalized traces,
fixture databases and archived grader outputs. Those local artifacts are not
committed. The curated JSON snapshot above is committed with this report.

| Case | Run ID | Task window, UTC | Evidence |
| --- | --- | --- | --- |
| B01 | `pair-20260918T140003-27b43f4300` | 14:00:58–14:01:17 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B01-c81e4b6bbb7e/runs/pair-20260918T140003-27b43f4300/report.html) |
| B02 | `pair-20260918T140117-14b228f2ca` | 14:01:56–14:02:09 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B02-c3ec09371000/runs/pair-20260918T140117-14b228f2ca/report.html) |
| B03 | `pair-20260918T140209-f4fa533929` | 14:02:41–14:03:00 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B03-acb28d925522/runs/pair-20260918T140209-f4fa533929/report.html) |
| B04 | `pair-20260918T140300-5f307f2011` | 14:03:31–14:03:54 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B04-804de6e45f46/runs/pair-20260918T140300-5f307f2011/report.html) |
| B05 | `pair-20260918T140354-94400f18a5` | 14:04:28–14:05:03 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B05-2c45e7663c80/runs/pair-20260918T140354-94400f18a5/report.html) |

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

Current conclusion: **this default-model smoke run does not support faster,
cheaper or more accurate tool selection with Rippletide**. It measured increased
time/tokens and exposed wrong selections in B01, B02 and B04. B02's execution
stayed safe because Codex declined the recommendation; B01 recovered its answer.
B04 did not obtain the required current time and did not answer correctly.

The intended handoff was observable: Codex requested choices, Qwen selected
capabilities, and fixture tools executed. That demonstrates integration, not
usefulness or universal coverage. B03 shows correct selected tool execution;
B05 shows recovery with additional routing overhead. Zero human corrections in
all ten attempts does not establish the success-without-intervention target,
because failures and unknown acceptance remain in the denominator.

Next experiment prerequisites (not implemented in this report-only follow-up):

1. Correct trace accounting for pure catalog discovery and failed tool results,
   with negative tests; retain these original unknown grades.
2. Fix the sole-candidate relevance shortcut and test temporal/prerequisite
   selection using cases separate from model tuning data.
3. Run a new versioned experiment, then sequential alternating repetitions for
   less-contended timing and repeatability evidence. One attempt cannot measure
   determinism; deterministic decoding alone does not establish workflow stability.

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
| 2026-09-18 | Committed `dac1c61`, installed its plugin and ran B01–B05 with default Codex and router choices. | Five real pairs / ten completed processes; all automatic grades unknown due to trace-accounting gaps. Original evidence retained; time/tokens and inspected behavior reported above. |
