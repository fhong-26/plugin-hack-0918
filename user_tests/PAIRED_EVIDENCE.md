# Paired evidence and grading

Paired runs keep four independent dimensions: tool-choice correctness, observed
execution success, configured task-acceptance checks, and routing compliance.
Process exit zero is not proof of a correct task or a compliant routing workflow.

`report_pair(run)` writes and returns a sharing-oriented report. `report.json`,
`report.md`, and offline `report.html` use an allowlist: no task prompt, arbitrary
arguments, result snippets, custom tool names, paths, credentials, or free-text
judge explanations are exported. Tools retain useful operation classes and stable
ordinal aliases. Unlinked decisions, unknown executions, hook failures, blocked
attempts, outside-coverage actions, and incomplete usage remain visible.

`evidence-private.json`, `pair.json`, raw session logs, and `judge/` contain private
evidence. Do not share these as sanitized reports. Generated evidence files use
mode `0600`; generated judge directories use `0700`. HTML is escaped, contains no
JavaScript or remote resources, and includes a restrictive content policy.

## Independent judge

`grade_pair(run, codex=..., environment=..., model=None, effort=None, timeout=180)`
runs **after** both task arms have stopped. It rejects an arm marked `running`.
The caller supplies an isolated Codex environment; no MCP tools, browsing, or
plugins are configured for the judge. The invocation uses `--sandbox read-only`,
`--ignore-user-config`, `--ignore-rules`, approval policy `never`, and a JSON output
schema. A judge that invokes tools is rejected, even if it emits plausible grades.
These CLI behaviors are grounded in the [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

Each choice gets a **separate process and input card**. It sees the initial goal,
available tool descriptions, selected tool/arguments, and only observations made
before that choice. It cannot see the current call's result, future observations,
another choice card, routing labels, final patches, or hidden reasoning. Context
is bounded to the last eight prior observations, with truncation disclosed. The
frozen rubric permits multiple reasonable tools and grades arguments separately
from tool choice. The labels are `correct`, `incorrect`, `uncertain`, and
`ungradable`; automated labels are always provisional.

Defaults bound cost: **12 choices**, **2 concurrent judge processes**, and **180
seconds total wall-time budget**. The `environment` passed to `grade_pair` may set
`RIPPLETIDE_JUDGE_MAX_CHOICES` (0–100) and `RIPPLETIDE_JUDGE_CONCURRENCY` (1–4).
Selection is deterministic and balanced between arms (six each at the default
cap when available). Registered choices come first; native search, MCP lookup,
and agent assignment are each represented before remaining slots are sampled.
No execution outcomes or grades affect selection. If one arm lacks enough choices,
unused slots can go to the other; the allocation is recorded. Legacy unbalanced
samples are explicitly exploratory, not retroactively presented as balanced. Choices
outside the cap, missing outputs, exhausted time budgets, and invalid judgments
remain explicitly ungradable. The report exposes grading coverage and limits;
partial grading must not be represented as an exhaustive comparison.

`correctness.json` points to the latest grading attempt. `judge/<attempt>/` keeps
the inputs, schema, stdout/stderr, per-choice results, identity mapping, and frozen
rubric hash. Judge time and all observed judge tokens, including failed attempts,
are accounted separately from task execution. Missing failed-attempt usage is
incomplete, not zero. No token categories are converted to money automatically.

## Auditing and interpretation

`audit_grade(run, call_id, verdict, reason)` appends to `correctness-audit.jsonl`;
it does not overwrite automated grades. The anonymous `choice_...` audit ID from
the shared timeline is accepted, as is a unique raw call ID or a canonical
`arm:session:call` identity. Reports retain prior judgments privately and label
the effective audited verdict `human-reviewed`. Fixture labels, when explicitly
provided with evidence in `fixture-grades.jsonl`, have separate `fixture-approved`
provenance; they are never inferred from an automated judge's confidence.

External independent acceptance checks may approve their configured assertions.
Repository-owned checks are labeled provisional, and neither implies that the
entire task specification was proven. Unknown tool execution does not imply an
incorrect tool choice; conversely a successful call can still be the wrong choice.
Routing authorization and blocked attempts are distinguished from execution.

## Token accounting

For recent Codex rollouts, response IDs identify unique per-thread usage; these
are checked against the thread counter. For older rollouts, cumulative snapshots
are deduplicated per session and converted to deltas with a proven starting
balance. Replayed parent history and inherited child history are not charged
twice. A resumed parent log is not added to its earlier prefix as a second bill.
Raw and CLI usage are alternatives, never summed together for the same session.

Every discovered child must have its own scoped rollout for complete coverage.
Missing children, unrelated logs, unresolved task-path identities, unknown initial
balances, partial sessions, or ambiguous multiple-turn CLI usage produce incomplete
coverage. Cached input and reasoning output are subsets, not extra totals to add.
Local router input/generated/readout counts are reported separately when emitted.

Hook events can expose concrete calls inside a generic host `exec` container.
The container itself is not graded as an extra tool choice. Native exit status
missing from a hook is supplemented only by a unique exact command-and-result
match in the host CLI output; repeated or ambiguous matches stay unknown. Modern
agent completion is linked through task path, named role, parent/child metadata,
and structured child completion—not prose or an opaque message's contents.

One pair is an observation, not evidence of statistically reliable speed, cost,
quality, or autonomy gains. Compare matched settings and sufficient repeated tasks
before making product claims.
