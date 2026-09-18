# Rippletide — Product Requirements Document

Status: Draft v0.1 · Date: 2026-09-18

Source: [Original ChatGPT response](/Users/fanhong-rippletide/projects/plugin-hack-0918/chatgpt-response-prd-source.md).

## 1. Product description

Rippletide is a Codex plugin that delegates routine tool choices to explicit rules and a small local model. It follows developer preferences while Codex handles task reasoning, tool arguments, execution, and coding. The MVP chooses how to search a repository. Its intended benefits are more consistent decisions, less wasted work, and lower task time and token usage.

These benefits are hypotheses to validate, not current performance claims.

## 2. User and problem

Target user: a developer using Codex across repositories with different tools and conventions.

User story: “When Codex searches my codebase, I want it to choose an appropriate method and remember my preferences, so I spend less time correcting it.”

Initial problem: repeated choices between filename, exact-text, and semantic search can produce inconsistent behavior or unnecessary calls.

## 3. MVP scope

### Included

- An installable Codex plugin for local Apple Silicon Macs using MLX; document the supported Codex version and runtime requirements.
- A routing skill and local Python router, exposed through an MCP tool. MCP is internal integration; the user installs Rippletide as a plugin. This packaging is supported by the [official plugin architecture](https://developers.openai.com/plugins/concepts/plugins).
- Three registered search routes: filename/path search, lexical search using `rg`, and one existing semantic-search integration when configured and available.
- Explicit user/project preferences, bounded model decisions, fallback to Codex, local decision logs, and a compact report available on request.
- A reproducible evaluation harness comparing routing quality and complete coding tasks.

### Required small model

Use the user-selected [harshatheg/Qwen-2.5-1B-RLCD](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD) project as the MVP inference backend. Its model card describes an MLX constrained-decoding engine configured with `mlx-community/Qwen2.5-1.5B-Instruct-4bit`; record that actual weight identity despite the project's “1B” name.

The integration milestone must verify runnable artifacts, pin the engine and weight revisions, and demonstrate real inference. Keep the model loaded between requests. An unavailable backend produces a visible readiness failure or routing fallback; it must not silently select a different model. Published model-card benchmarks are not Rippletide acceptance results.

### Excluded

Routing every Codex tool; replacing Codex's internal reasoning loop; generating tool arguments with Qwen; executing tools inside the router; building a semantic index engine; hosted inference; Windows/Linux support; automatic fine-tuning or RL; a standalone dashboard.

Choose and document one semantic provider during the integration milestone. A configured provider is required in the evaluation environment; ordinary projects can run with the remaining routes when it is absent.

## 4. User flow

1. **Install and set up.** The developer installs Rippletide and completes a one-time model download/readiness check. Setup shows available search methods and any missing prerequisites.
2. **Enable for a project.** The developer reviews detected settings and can set preferences such as “exact search first when a symbol is known.”
3. **Ask Codex normally.** Example: “Find why expired sessions remain active and fix it.”
4. **Get assisted search.** Rippletide recommends the search method. Codex supplies arguments, searches, and continues investigating. Routine recommendations need no additional user confirmation; existing execution permissions apply.
5. **Continue through uncertainty.** If Rippletide cannot decide or is unavailable, Codex continues independently without repeatedly requesting the same decision.
6. **Correct and inspect.** The developer can make a one-off correction or explicitly save a project preference. An on-request report shows decisions, rule/model sources, fallbacks, overrides, and measured routing time.

## 5. Decision behavior and integration

The MVP uses an explicit handoff: Codex identifies an immediate search goal, calls Rippletide, then generates the selected tool's arguments. Recommendations are advisory; record overrides rather than claiming enforcement.

The documented `PreToolUse` hook already receives a tool name and its arguments. Consequently, this PRD does not depend on a hook pausing Codex between internal tool selection and argument generation. See the [official hooks documentation](https://learn.chatgpt.com/docs/hooks).

| Stage | Required behavior |
| --- | --- |
| Request | Codex supplies the immediate goal, optional symbol/path, and up to two recent search observations. It does not enumerate candidates. |
| Context | The plugin adds registered available routes, short descriptions, project facts, and preferences. Cap the model input at 1,024 tokens; omit old observations first and defer if essential information cannot fit. |
| Rules | Filter unavailable/disallowed routes. Honor explicit instructions for the current task, then project preferences, then user defaults. Select immediately when a rule settles the choice or only one suitable route remains. |
| Model | For unresolved choices, use the required Qwen backend to select from the remaining route IDs or `defer`. Use fixed decoding settings; tune any acceptance threshold on development data only. Model scores are not assumed to be calibrated confidence. |
| Response | Return `decision_id`, `status`, `route_id` when selected, `source`, `reason_code`, and registry version. Attach the actual tool mapping and argument schema from the registry, never model-generated schemas. |
| Continue | Codex generates arguments and executes the real tool. Logical routes can map to the same shell tool with different commands. Unknown IDs, insufficient context, errors, or a two-second router deadline produce a fallback. |
| Record | Log versions, timing, decision source, and observed feedback locally. Associate subsequent outcomes with the decision where available; mark unobserved outcomes as unknown. |

The registry covers explicitly integrated tools; automatic discovery of every native Codex tool is not assumed. Repository text and tool output are data and cannot change preferences or registered candidates. Feedback updates configuration only when the user explicitly asks for a lasting preference. MVP feedback does not retrain the model.

## 6. Test use cases

| ID | Scenario | Expected result |
| --- | --- | --- |
| T01 | Fresh installation and two unresolved routing requests | Required engine/weight revisions load; real model inference runs; the second request reuses the loaded model. |
| T02 | Find `validate_identity` with exact-search preference | Lexical route selected by rule; Codex generates valid arguments and finds the expected definition. |
| T03 | Find a known filename such as `session_store.py` | Filename/path route selected; result includes the expected file. |
| T04 | Locate session-expiration logic without a symbol, with semantic search available | Model chooses a human-approved route; integration test retrieves relevant code. More than one route may be acceptable. |
| T05 | Exact search returned no matches | Recent failure reaches the router; it chooses an appropriate alternative or defers instead of blindly repeating the failed search. |
| T06 | Semantic provider missing or unavailable | Semantic route is excluded. If explicitly required by the user, return a clear fallback instead of claiming it ran. |
| T07 | Task instruction conflicts with project/user preferences | Task instruction wins within available/permitted routes; a saved project preference applies to the next request. |
| T08 | Missing goal, unsupported operation, or no suitable tools | Structured fallback with a reason; Codex proceeds without a routing loop. |
| T09 | Model crash, unloaded backend, or inference timeout | Readiness/error is reported; pending routing request falls back within two seconds. A connection failure also causes Codex to continue. |
| T10 | Invalid model output or unknown route ID | Validation rejects the recommendation; no nonexistent or disallowed tool is proposed. |
| T11 | Repository text says to override policy or use an unregistered tool | Text remains data; registered candidates and explicit preferences remain effective. |
| T12 | Identical packet, versions, tool availability, and decoding settings | Repeated choices meet the consistency target below. |
| T13 | Developer overrides a recommendation | Codex can continue; override is recorded separately from router acceptance. |
| T14 | Complete an expired-session bug fix | Codex uses routing, finds relevant code, edits it, and passes independent task acceptance tests; full time and usage are captured. |

## 7. Evaluation and success criteria

All thresholds below are proposed MVP targets, not measured results. Freeze them and the reference hardware before the final evaluation.

Compare four variants: **A** Codex alone; **B** Codex with clear routing instructions; **C** Codex with a rules-only router and Codex fallback; **D** Codex with rules plus the required Qwen backend.

Use at least 200 held-out labeled decisions and 40 complete tasks across at least five repositories. Keep tuning repositories separate. Labels specify all acceptable routes and cases requiring fallback. Run each complete task three times per variant with the same Codex settings, repository starting state, available tools, and acceptance tests; randomize run order. Report variability and failures, not only averages.

| Measure | MVP target |
| --- | --- |
| Contract and preference correctness | 100% of responses validate; no unavailable/disallowed selections; all explicit-preference tests pass. |
| Decision quality | At least 90% of selected routes match a human-approved label, with selection on at least 80% of answerable held-out requests. Report model-only accuracy and all fallbacks separately. |
| Model contribution | D selects at least 10 percentage points more answerable requests than C, while maintaining the decision-quality target. This tests whether Qwen adds value beyond rules. |
| Repeatability | At least 99% agreement with each packet's modal decision across 10 runs of 100 fixed packets. Report ties and rule/model results separately. |
| Router latency | Warm request p95 at most 500 ms, including context preparation and inference, on the declared Apple Silicon reference machine. Report cold startup separately; enforce the two-second deadline. |
| Complete-task quality | D's observed task-success rate is at least A's and the strongest B/C baseline's rate. Success is determined by independent task acceptance tests. |
| Time and token savings | D reduces median complete-task time and mean Codex tokens per completed task by at least 10% versus A. Include failed attempts, routing requests, retries, fallbacks, and all reported token categories; report results against B/C as well. |

For time comparisons, use tasks completed by both variants and publish completion rates alongside them. Tokens per completed task equals all tokens spent in an evaluation variant, including failures, divided by completed tasks. Also report cached-token usage and estimated billed cost when available, plus local inference time and memory; token reductions alone do not establish monetary savings. Claims remain provisional when run-to-run uncertainty could erase the observed gain.

Engineering completion and product success are separate decisions: a working plugin can miss the performance targets. If D offers no useful improvement over B/C, document that result before expanding scope or investing in training.

## 8. Definition of done

- [ ] Plugin installs and completes the documented setup on the declared Codex/macOS configuration.
- [ ] The exact requested Hugging Face backend performs real inference; engine and weight revisions and startup behavior are recorded.
- [ ] All three routes work in the evaluation environment; availability filtering, preferences, and fallback behavior are implemented.
- [ ] Codex completes the request → recommendation → argument generation → execution flow, including override and failure paths.
- [ ] T01–T14 pass their functional assertions; repeatability/performance measurements are reported against their targets.
- [ ] Local traces and an on-request report show actual decisions and timings; unavailable usage/outcome data is identified.
- [ ] The four-variant evaluation is reproducible, with fixtures, labels, settings, raw results, and a report showing pass/fail against every success criterion.
- [ ] Installation, configuration, supported tools, limitations, disable/uninstall steps, and data locations are documented.

The MVP is engineering-complete when this checklist is satisfied. It is product-validated only when the success criteria are also met.

## 9. Delivery sequence

1. **Integration proof:** verify the requested model artifacts and one full Codex routing handoff; select the semantic integration and reference hardware.
2. **Functional MVP:** add the three routes, rules, model selection, preferences, fallback, and traces; pass functional tests.
3. **Evaluation:** freeze datasets and settings, run A–D, and publish the result against the targets.
4. **Next decision:** expand only where results support it. Fine-tuning on reviewed corrections and RL remain later work.
