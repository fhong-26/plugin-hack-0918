# Benchmark-derived user tests — latest experiment report

Updated 2026-09-18 after the user's main-branch changes. This report replaces the
previous current summary. The [previous report](BENCHMARK_EXPERIMENT_REPORT-2026-09-18-before-no-defer.md)
and [previous metrics](results/benchmark-smoke-2026-09-18-before-no-defer.json) are
archived; all original raw runs remain intact.

## Result in brief

Five new paired cases ran with default model choices. All ten task processes
completed without corrective human input, but **automatic acceptance remains
unknown in every arm** because of existing trace-accounting gaps.

The enabled arm used **114.470 seconds vs 47.106 seconds** of summed task time
(**2.43×**) and **529,648 vs 221,965 Codex tokens** (**2.39×**). It was slower in
all five pairs and used more tokens in four; B02 used 210 fewer tokens.

The rerun does not demonstrate improvement. Wrong choices remain in historical
weather and reminder lookup. Forecast and messaging tasks recovered through
Codex-supplied preference overrides, which must not be counted as successful
Qwen choices. These observations are not a certified pass rate or official
benchmark score.

[Current machine-readable evidence](results/benchmark-smoke-2026-09-18.json)
contains per-case metrics, requests → selections → linked call IDs, actual
fixture calls, final responses, state observations and provenance.

## How the test set was constructed

We hand-selected **three BFCL cases and two ToolSandbox scenarios before running
the experiments**, covering five distinct behaviors: choosing between similar
tools, rejecting an irrelevant tool, completing multiple calls, obtaining a time
prerequisite, and recovering a state-changing workflow. This is a small diagnostic
set, not a random or representative sample of either benchmark.

- **Source material:** retained the original public requests and tool definitions
  from pinned upstream revisions, with source hashes and licenses in the
  [source catalog](../user_tests/src/rippletide_uat/benchmarks/catalog.json).
- **Executable environment:** adapted tool names/types to MCP and implemented
  local tools with isolated SQLite state, synthetic responses and a fixed fixture
  clock where needed. No real weather, shopping or messaging service was used.
- **Ground truth:** derived local checks from BFCL reference calls/no-call rules
  and ToolSandbox prerequisite milestones, expected content and resulting state.
  Added explicit local safety checks, such as exactly one message. These are
  adapted checks, **not the official benchmark evaluators**.
- **Fair comparison:** created fresh workspaces and databases for each arm, using
  the same request, task tools and starting data. Expected answers and graders
  stayed outside the presented project workspaces. The fixtures and checks were
  frozen before execution and unchanged between the two reported suites.

## What was tested

| Item | Configuration |
| --- | --- |
| Imported main | `8d60042af31e81dfb6239895303548ee23486752` — merges removal of model-level defer |
| Tested integration commit | `631d8b904d7133a964a22a3e9eb352f943d98dfc` on `feat/benchmark-user-scenarios` |
| Source state | Clean for all five pairs; existing benchmark harness retained |
| Installed plugin | `0.1.0+codex.20260918141216`; staged/validated/reinstalled through plugin-creator, source checked in private sessions |
| Codex | Repository-pinned CLI `0.155.0`; model/effort unset; observed model `gpt-6-astra` in both arms of every pair |
| Effort | Not explicitly emitted; no particular level inferred |
| Router | Default `qwen25-rlcd`, MLX, allowed-token argmax, no sampling |
| New router prompt | `v2-forced-semantic-labels`, observed in actual installed-model status for every pair |
| Engine / weights | RLCD `2af86848be75847ccb3553b0941cc51d6ef7e4e9` / MLX Qwen2.5-1.5B `8b403126fc14f14cfc99bb4cfa72ecbc129ea677` |
| Mode | One parallel pair per case; cases run sequentially; same Mac |
| Oracle | Unchanged local adapted reference/milestone checks; official upstream evaluators not run |

The imported change removes the model's defer label and changes selection
wording. Technical fallbacks remain possible. The sole-candidate rule, preference
override path and trace-accounting code were not fixed by that change.

Public task prompts, tool catalogs, initial fixture state and permissions matched
within pairs. Adapter/grader hash remained
`eb1b3ea6ae6d94915d68c376f2a08349a6794b39b8c96d79c4e9362dce56738d`,
identical to the earlier experiment. No product/oracle changes were made mid-run.
The source catalog retains five entries and 17 source-file hashes from pinned
BFCL and ToolSandbox revisions; see the [scenario definitions](BENCHMARK_USER_SCENARIOS.md)
and [adaptation limits](../user_tests/BENCHMARKS.md).

Command used, with no model overrides:

```sh
uv run --locked --project user_tests rippletide-uat benchmark run --cases B01 B02 B03 B04 B05
```

## Measured task metrics

Seconds include the measured task process and routing round trips, but exclude
preflight. Token totals are Codex input + output across observed parent/child
sessions. Cached input is already included in input. Token coverage is complete
for all ten task sessions; tool-trace completeness is a separate limitation.

| Case | Native seconds | Rippletide seconds | Native total tokens | Rippletide total tokens | Required interventions, native / enabled |
| --- | ---: | ---: | ---: | ---: | --- |
| B01 | 7.616 | 22.644 | 35,937 | 81,297 | 0 / 0 |
| B02 | 7.284 | 10.544 | 37,337 | 37,127 | 0 / 0 |
| B03 | 11.289 | 23.490 | 36,381 | 117,107 | 0 / 0 |
| B04 | 8.501 | 21.845 | 49,963 | 88,386 | 0 / 0 |
| B05 | 12.416 | 35.947 | 62,347 | 205,731 | 0 / 0 |
| Sum | 47.106 | 114.470 | 221,965 | 529,648 | 0 / 0 |

The time sum is not total elapsed suite duration; the two arms run concurrently.
Shared hardware, cache and service scheduling prevent an isolated latency claim.

| Accounting category, five cases | Native | Rippletide |
| --- | ---: | ---: |
| Task input tokens | 220,972 | 526,464 |
| Of which cached input | 156,347 | 446,261 |
| Non-cached input, by subtraction | 64,625 | 80,203 |
| Task output tokens | 993 | 3,184 |
| Setup/preflight tokens, separate | 352,859 | 458,134 |
| Setup/preflight wall seconds, summed | 94.577 | 90.949 |
| Planned task prompts | 5 | 5 |
| Required corrective interventions | 0 | 0 |

No optional model judge ran. No monetary cost or saving is inferred from these
counts. Zero corrective interventions does not establish successful completion
without intervention when incorrect behavior and unknown acceptance remain.

### Local routing overhead and sources

| Case | Model decisions | Rule decisions | Recorded routing milliseconds, sum | Rule reasons |
| --- | ---: | ---: | ---: | --- |
| B01 | 2 | 0 | 166.566 | None |
| B02 | 0 | 1 | 0.496 | `ONLY_CANDIDATE` |
| B03 | 4 | 1 | 467.727 | `TASK_PREFERENCE` |
| B04 | 3 | 0 | 426.243 | None |
| B05 | 5 | 1 | 522.353 | `TASK_PREFERENCE` |
| Total | 14 | 3 | 1,583.385 | One sole-candidate choice; two preference overrides |

The local model recorded 1,850 input tokens, 14 label readouts and zero
autoregressively generated output tokens. Cold worker startup observed during
preflight ranged from 3.32 to 4.08 seconds. No technical fallback occurred.
Small-model latency alone does not include the extra Codex turns around routing.

## Scenarios, ground truth and observed behavior

These are inspections of actual calls, requests, responses and fixture state.
They **do not override** the automatic unknown grades.

### B01 — Historical weather, not a forecast

Source: BFCL `multiple_5`. The user wants wind speed and temperature at
coordinates `[46.603354, 1.888334]` on `2019-12-13`.

Possible tools: city/date historical weather, coordinate forecast, and
coordinate/date historical weather. The right behavior is one
`weather.get_by_coordinates_date` call with that date and those coordinates.

- Native: chose the historical-coordinate function immediately and returned
  7.25°C and 18.5 km/h from the synthetic fixture.
- Enabled: Qwen chose `weather.get_forecast_by_coordinates`; Codex executed it.
  After feedback that a forecast could not answer the request, Qwen chose the
  historical function and the final response recovered.
- Interpretation: the extra forecast is a wrong selection and violates the
  exact reference-call multiset even though the final answer is correct.
  Both states remained unchanged. This behavior also occurred before the change.

### B02 — Find a bookstore without purchasing

Source: BFCL `irrelevance_55`. The user asks which online bookstore sells
*To Kill a Mockingbird*. The only available tool is `add_product_to_cart`.

Right behavior: no task-tool call; explain that the available capability cannot
search bookstores or availability, and keep the cart unchanged.

- Native: no cart call; explained the limitation.
- Enabled: `ONLY_CANDIDATE` selected the cart tool without Qwen inference.
  Codex declined to call it and explained the limitation. State stayed unchanged.
- Interpretation: favorable task behavior came from Codex refusing a wrong rule
  recommendation, not from Qwen recognizing irrelevance. The tiny token advantage
  in this one run is not proof of general savings.

### B03 — Obtain all three forecasts

Source: BFCL `parallel_multiple_32`. The user wants ten-day Boston, USA
temperature and humidity, plus ten-day Rome, Italy precipitation.

Possible tools: `weather_forecast_temperature`, `weather_forecast_humidity`,
`weather_forecast_precipitation`. Right behavior: all three reference calls,
correct city and `days=10`, any order, no missing or duplicate calls.

- Native: executed all three required functions with correct arguments.
- Enabled: Qwen chose temperature correctly, then chose temperature twice for
  humidity requests. Those two recommendations were not executed. It subsequently
  chose precipitation correctly. Codex finally supplied
  `preferred_route="mcp.fixture.weather_forecast_humidity"`, producing a
  `TASK_PREFERENCE` rule selection and the remaining call.
- Both final answers contained the three labelled forecast series, and the
  actual call multiset had no extra calls. State stayed unchanged.

A representative request/choice sequence:

| Codex's immediate request | Rippletide choice | Source | Execution |
| --- | --- | --- | --- |
| Get temperature forecast for Boston | Temperature | Model | Executed |
| Get humidity forecast for Boston | Temperature | Model | Not executed |
| Retrieve daily relative humidity; temperature already retrieved | Temperature | Model | Not executed |
| Get precipitation forecast for Rome | Precipitation | Model | Executed |
| Retrieve humidity, with explicit `preferred_route` supplied by Codex | Humidity | Rule / TASK_PREFERENCE | Executed |

The automated `router_choice=correct` for B03 is only **reference-function
membership**: temperature is somewhere in the overall required set. It does not
mean temperature was correct for the humidity subgoal. The goal-level mismatch
and preference override are retained in the snapshot and raw traces.

### B04 — Resolve “upcoming” against the current time

Source: ToolSandbox `search_reminder_with_recency_upcoming`. The user asks
for their upcoming reminder.

Possible tools: `get_current_timestamp`, `search_reminder`,
`shift_timestamp`, `timestamp_to_datetime_info`. Right behavior: obtain the
fixture clock, use it as the search lower bound within one second, and return
“Buy a nice rich navy bathing dress.”

- Native: read `1778846400`, searched with that lower bound, and returned the
  expected reminder in 30 minutes.
- Enabled: Qwen chose search, then shift, then shift across three requests for
  current time. Only the search executed, with lower bound `0`; no clock call
  occurred. The final answer named the past library-book reminder, while admitting
  it could not confirm that it was upcoming.
- Interpretation: missing prerequisite and wrong answer, not successful
  completion. State remained unchanged. Removing model defer did not resolve
  this observed failure.

### B05 — Send one simulated message despite service being off

Source: ToolSandbox `send_message_with_contact_content_cellular_off`. The
user wants the message “How's the new album coming along.” sent to Fredrik
Thordendal, resolving issues without asking for help.

Possible tools: `search_contacts`, `get_cellular_service_status`,
`set_cellular_service_status`, `send_message_with_phone_number`.
Right behavior: resolve the contact and enable cellular service before a
successful send; create exactly one intended message and no unrelated changes.

- Native: looked up the contact, checked service status, enabled service, then
  sent successfully. Four calls; no failed send.
- Enabled: looked up the contact, attempted to send twice while service was off,
  and received two errors. Qwen kept choosing send for requests to enable service.
  Codex supplied `preferred_route="mcp.fixture.set_cellular_service_status"`;
  the rule then enabled service and a final Qwen-selected send succeeded.
- Both ended with exactly one message to the synthetic number `+12453344098`
  containing the requested text, service enabled and no unrelated state changes.
  Both confirmed the send. The two failed sends remain in the evidence.

Recovery here was not solely small-model-driven: the necessary enable-service
choice came from a Codex preference override.

### Preference provenance is a separate limitation

The B03 and B05 public tasks did not explicitly select named capabilities.
The routing skill reserves `preferred_route` for explicit user tool choices,
yet Codex supplied it to resolve repeated bad recommendations. The router
accepted those values as `TASK_PREFERENCE`.

This is an observed routing-contract/provenance gap, not a human correction,
not a technical fallback, and not proof that Qwen chose the recovery tool.
Guard authorization only proves the call matched the returned receipt; it does
not validate where the claimed user preference originated.

## Why automatic acceptance is still unknown

All ten sessions used host containers to inspect `ALL_TOOLS`. Pure catalog
discovery has no nested tool hooks; the conservative completeness gate flags one
such container per session, except native B02 with two. The recorded snippets
were inspected as discovery, but the frozen grader was not relaxed after seeing
the answers.

Enabled B05 has an additional failure-correlation gap: five fixture events,
including two send errors, versus only three fixture `tool_completed` hooks.
Native B05 has four successful events and four completion hooks.

Consequently, the suite command exited **1**. All ten automatic local grades
remain `unknown`, and full-trace verified-model-execution counts remain null.
Specific observed wrong calls/answers are still reportable; unknown is neither
a passing score nor proof that every task failed. Official upstream scores
remain null. This experiment does not validate a pass-rate target.

## Comparison with the previous implementation

| Aggregate, five cases | Before: native | Before: enabled | After: native | After: enabled |
| --- | ---: | ---: | ---: | ---: |
| Task seconds | 60.077 | 109.108 | 47.106 | 114.470 |
| Codex task tokens | 220,837 | 461,391 | 221,965 | 529,648 |
| Corrective human interventions | 0 | 0 | 0 | 0 |
| Automatic acceptance | Unknown | Unknown | Unknown | Unknown |

Enabled task time increased descriptively by 4.9% and tokens by 14.8%.
The baseline's timing also changed substantially. These are one suite per
version, not repeated controlled estimates, and do not establish a causal
regression or improvement.

The previous run had **zero model deferrals and zero technical fallbacks**.
Thus this comparison cannot show savings from removing previously observed defer
events; the changed prompt/allowed labels and Codex trajectories are also factors.
Both versions' runs remain visible: ten pairs / twenty started tasks in total,
with no attempt discarded or favorable-only selection.

## Latest run ledger and raw reports

Every pair below used clean integration commit `631d8b9`, the same default
models, unchanged fixtures/graders and parallel arms. No pair was setup-blocked
or timed out. HTML links are local presentation reports; each directory also
contains Markdown/JSON reports, private requests/results/session traces, SQLite
fixture state and archived grades. Raw artifacts remain outside Git.

| Case | Run ID | Measured task window, UTC | Evidence |
| --- | --- | --- | --- |
| B01 | `pair-20260918T141304-5cc0de6ab6` | 14:13:46–14:14:08 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B01-d855ff85ad0b/runs/pair-20260918T141304-5cc0de6ab6/report.html) |
| B02 | `pair-20260918T141409-6828b97f10` | 14:14:45–14:14:56 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B02-999ed09da76f/runs/pair-20260918T141409-6828b97f10/report.html) |
| B03 | `pair-20260918T141456-ad1ea17b4e` | 14:15:30–14:15:54 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B03-3e26db259329/runs/pair-20260918T141456-ad1ea17b4e/report.html) |
| B04 | `pair-20260918T141554-a44c933b8d` | 14:16:38–14:16:59 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B04-076bdc5bb673/runs/pair-20260918T141554-a44c933b8d/report.html) |
| B05 | `pair-20260918T141700-1bee597807` | 14:17:35–14:18:11 | [Report](/Users/fanhong-rippletide/.local/share/rippletide/uat/benchmarks/benchmark-B05-7b52f2232e68/runs/pair-20260918T141700-1bee597807/report.html) |

The current JSON snapshot preserves these run IDs and hashes. The
[archived report](BENCHMARK_EXPERIMENT_REPORT-2026-09-18-before-no-defer.md)
links every original run; this update overwrites only the current summary/data
paths, not raw experiments.

## Verification and next steps

After merging main and before the measured tasks:

| Check | Result |
| --- | --- |
| Plugin runtime/guard suite | 71 passed; 13 opt-in checks skipped |
| Test-kit suite | 150 passed |
| Repository unittest suite | 17 passed; 2 optional checks skipped |
| Plugin manifest validation and install | Passed; previous staged copy backed up |
| Per-pair readiness | Both arms ready; model/settings equality observed |
| Automatic scenario acceptance | Unknown for all ten arms; command exit 1 |

No speed, monetary-saving, general accuracy or determinism claim is supported.
For a useful next version: fix trace completeness for discovery/failure results,
validate preference provenance, correct the sole-candidate relevance shortcut,
and improve temporal/prerequisite selection. Keep these original outcomes and
use new versioned runs after fixes; do not retroactively change the oracle.
Sequential alternating repetitions would give cleaner timing comparisons.
