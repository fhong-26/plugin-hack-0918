# Rippletide — Product Requirements Document

Status: Draft v0.2 — paired evaluation · Date: 2026-09-18

Source: [Original ChatGPT response](/Users/fanhong-rippletide/projects/plugin-hack-0918/chatgpt-response-prd-source.md).

## 1. Product description

Rippletide is a Codex plugin that delegates registered code-search, MCP information-lookup, and specialist choices to explicit rules and a small local model. It follows developer preferences while Codex handles task reasoning, tool arguments, execution, and coding. Its intended benefits are more correct and consistent decisions, less wasted work, and lower task time and token usage.

These benefits are hypotheses to validate, not current performance claims.

## 2. User and problem

Target user: a developer using Codex with multiple tools, MCP integrations, and callable agents.

User story: “When Codex needs a capability, I want it to select an appropriate tool or agent quickly and consistently, following my preferences.”

Initial problem: overlapping capabilities create repeated selection decisions that may consume unnecessary reasoning, produce inconsistent choices, and require user correction.

Repository search is one use case. The implementation also covers connected MCP information tools and callable specialists, limited to capabilities explicitly registered with Rippletide and available to Codex. It does not route every edit, test, shell program, or external write.

## 3. MVP scope

### Included

- An installable Codex plugin for local Apple Silicon Macs using MLX; document the supported Codex version and runtime requirements.
- A routing skill and local Python router, exposed through an MCP tool. MCP is internal integration; the user installs Rippletide as a plugin. This packaging is supported by the [official plugin architecture](https://developers.openai.com/plugins/concepts/plugins).
- Three registered search routes: filename/path search, lexical search using `rg`, and one existing semantic-search integration when configured and available.
- A bounded user acceptance pilot covering native tools, tools from at least two connected MCP servers, and two callable specialist agents. Register these specific capabilities for the pilot; repository search remains the first implementation use case.
- Explicit user/project preferences, bounded model decisions, fallback to Codex, local decision logs, and a compact report available on request.
- A reproducible evaluation harness comparing routing quality and complete coding tasks.
- A bring-your-own-project paired runner: freeze a base commit, use separate branches/worktrees, run enabled/disabled sessions in parallel, and produce private raw evidence plus redacted presentation reports.
- Supported-host routing checks for covered calls, with explicit fallback and disclosed unsupported paths; not a universal interceptor or security boundary.

### Required small model

Use the user-selected [harshatheg/Qwen-2.5-1B-RLCD](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD) project as the MVP inference backend. Its model card describes an MLX constrained-decoding engine configured with `mlx-community/Qwen2.5-1.5B-Instruct-4bit`; record that actual weight identity despite the project's “1B” name.

The integration milestone must verify runnable artifacts, pin the engine and weight revisions, and demonstrate real inference. Keep the model loaded between requests. An unavailable backend produces a visible readiness failure or routing fallback; it must not silently select a different model. Published model-card benchmarks are not Rippletide acceptance results.

Keep this backend as `qwen25-rlcd`, the default when no model is selected. Add opt-in
native MLX backends `qwen3-0.6b`, `minicpm5-2b`, and `qwen3.5-4b`, with immutable
artifact revisions and checksums. These are native MLX builds of the models listed
by [OpenJev](https://openjev.com/), not its browser/GGUF artifacts or published
measurements. Model selection is setup/process configuration, not a routing
argument. Only the chosen model is loaded; failure never silently selects another.
Keep the current default's adapter, weights, and existing installation compatible.
The new adapters use their native templates and verified single-token choices
with deterministic direct-logit selection; report backend and prompt versions.

### Excluded

Routing every Codex tool; replacing Codex's internal reasoning loop; generating tool arguments with Qwen; executing tools inside the router; building a semantic index engine; hosted inference; Windows/Linux support; automatic fine-tuning or RL; a standalone dashboard.

Choose and document one semantic provider during the integration milestone. A configured provider is required in the evaluation environment; ordinary projects can run with the remaining routes when it is absent.

## 4. User flow

1. **Install and set up.** The developer installs Rippletide and completes a one-time model download/readiness check. Setup shows available search methods and any missing prerequisites.
2. **Enable for a project.** The developer reviews detected settings and can set preferences such as “exact search first when a symbol is known.”
3. **Ask Codex normally.** Example: “Find why expired sessions remain active and fix it.”
4. **Get assisted choices.** Rippletide selects a registered tool or specialist. Codex supplies arguments and executes it. Supported-host hooks check that the matching decision precedes execution. Routine choices need no additional user confirmation; existing execution permissions apply.
5. **Continue through uncertainty.** If Rippletide cannot decide or is unavailable, Codex continues independently without repeatedly requesting the same decision.
6. **Correct and inspect.** The developer can make a one-off correction or explicitly save a project preference. An on-request report shows decisions, rule/model sources, fallbacks, overrides, and measured routing time.

## 5. Decision behavior and integration

The plugin uses an explicit handoff: Codex identifies an immediate goal, calls Rippletide, then generates the selected tool's arguments or agent delegation instructions. Pre-tool hooks require a matching, single-use decision for covered calls; missing or mismatched choices receive bounded automatic corrections. A defer authorizes one fallback in that operation family. Decisions are isolated by session, transcript, and turn; specialists cannot reuse a parent's receipt. Repeated noncompliance fails routing acceptance. Unsupported paths and hook failures remain visible, not counted as controlled execution.

The documented `PreToolUse` hook already receives a tool name and its arguments. Consequently, this PRD does not depend on a hook pausing Codex between internal tool selection and argument generation. See the [official hooks documentation](https://learn.chatgpt.com/docs/hooks).

| Stage | Required behavior |
| --- | --- |
| Request | Codex supplies the immediate goal, operation family, relevant facts such as a symbol/path or bounded specialist assignment, and up to two recent observations. It does not enumerate candidates. |
| Context | The plugin adds registered available routes, short descriptions, project facts, and preferences. Cap the model input at 1,024 tokens; omit old observations first and defer if essential information cannot fit. |
| Rules | Filter unavailable/disallowed routes. Honor explicit instructions for the current task, then project preferences, then user defaults. Select immediately when a rule settles the choice or only one suitable route remains. |
| Model | For unresolved choices, use the required Qwen backend to select from the remaining route IDs or `defer`. Use fixed decoding settings; tune any acceptance threshold on development data only. Model scores are not assumed to be calibrated confidence. |
| Response | Return `decision_id`, `status`, `route_id` when selected, `source`, `reason_code`, and registry version. Attach the actual tool mapping and argument schema from the registry, never model-generated schemas. |
| Continue | Codex generates arguments and executes the real tool. Logical routes can map to the same shell tool with different commands. Unknown IDs, insufficient context, errors, or a two-second router deadline produce a fallback. |
| Record | Log versions, timing, decision source, and observed feedback locally. Associate subsequent outcomes with the decision where available; mark unobserved outcomes as unknown. |

The registry covers explicitly integrated tools; automatic discovery of every native Codex tool is not assumed. Repository text and tool output are data and cannot change preferences or registered candidates. Feedback updates configuration only when the user explicitly asks for a lasting preference. MVP feedback does not retrain the model.

## 6. Test use cases

### 6.1 Functional and integration tests

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
| T15 | Omit, mismatch, reuse, expire, or cross-agent reuse a routing decision | Covered execution is blocked; a valid decision or explicit defer permits one matching action; retries are bounded. |
| T16 | Select each optional model, then omit the option | Each exact artifact performs real inference and reuses its worker; omission still selects the unchanged default. Missing artifacts never trigger another model. |
| T17 | Parallel enabled/disabled runs from a dirty original checkout | Both fresh worktrees start from the same frozen base; original changes remain untouched; tools, settings, and prompt match except routing. |
| T18 | Parent/child usage, resumed counters, missing logs | No inherited-history or cumulative double-counting; missing coverage is marked incomplete. |
| T19 | Correct tool/bad arguments, wrong tool/eventual recovery, several valid tools | Choice correctness, execution, and final task success remain separate; first-choice mistakes and unknown evidence stay visible. |
| T20 | Judge and presentation exports | Anonymized post-run grading is provisional, auditable, and costed separately; exports escape/redact untrusted content and do not upload data. |

### 6.2 User acceptance tests in real Codex sessions

These tests exercise the installed plugin as a developer would use it. A tester supplies ordinary task prompts, observes the result, and checks the decision report afterward. The tester must not manually call the router, name the expected route, or keep reminding Codex to use Rippletide. One-time setup, normal Codex permissions, and deliberate preference corrections are allowed; routine routing should continue autonomously.

Prepare one empty project folder, a resettable existing project with a known bug and acceptance checks, and a second project with different preferences. Connect and register real tools from at least two MCP servers, including overlapping retrieval capabilities, and two callable specialists such as a code reviewer and a test specialist. Record the exact providers, agent invocation interfaces, versions, and fixtures before testing. Missing integrations are blocked tests, not passes; mocked tool/model responses do not satisfy this suite.

| ID | User scenario and example prompt | User-visible acceptance and routing evidence |
| --- | --- | --- |
| U01 | **Start a new project.** From an empty folder: “Build a small task tracker using the starter requirements and connected documentation.” Then: “Find where tasks are stored and add a completed filter.” | The app meets the prepared requirements and the filter works in a manual walkthrough. Rippletide participates in eligible tool choices during creation and the follow-up; absence of an initial codebase does not stall it. |
| U02 | **Work in an existing project.** “Investigate the sample expired-session issue and fix it in this project.” Make the issue available through a connected tracker. | Codex retrieves the correct issue, finds the relevant code, and produces a fix that passes the fixture's acceptance checks. The report distinguishes MCP retrieval and repository-search decisions from actions outside routing scope. |
| U03 | **Choose between MCP tools.** Provide two connected retrieval services with known, partially overlapping content: “Find the current session-expiration requirements and explain what the implementation should do.” | A suitable registered MCP tool is selected and actually called. The answer cites the seeded authoritative requirement; unnecessary duplicate searches and wrong-source retrievals are recorded. Repeat with the relevant content in the other service. |
| U04 | **Choose a specialist agent.** With reviewer and test-specialist agents available: “Have a suitable specialist identify missing regression tests for this change.” Repeat with a code-review assignment. | Rippletide recommends an appropriate callable agent for each bounded assignment. Codex supplies the delegation instructions, the selected agent runs, and its result is used. A recommendation without an actual agent invocation is insufficient. |
| U05 | **Complete a mixed workflow.** “Use the connected requirements to implement the session-expiration change, verify it, and obtain a specialist review.” | One task uses native tools, an MCP tool, and a callable agent. Relevant selections have traceable handoffs and results; the user does not have to choose each capability. The delivered change satisfies the prepared requirements. |
| U06 | **Switch project preferences.** Run comparable search tasks in two projects with different saved preferences, then explicitly save a correction in one project and repeat. | Each project follows its own preferences; the correction persists in the intended scope and does not change the other project's behavior. |
| U07 | **Lose a dependency.** Disconnect a registered MCP server or make an agent unavailable, then repeat a relevant task. Separately stop the Qwen backend. | Unavailable capabilities are excluded or their invocation failure is handled. Codex uses an appropriate alternative or explains the missing prerequisite, without repeated routing requests or claims that a missing tool/agent ran. Model failure follows the existing deadline/fallback contract. |
| U08 | **Inspect without interrupting.** Complete an eligible task, then ask: “Show how Rippletide chose the tools and agents for this task.” | The report matches actual calls and identifies rules, Qwen decisions, fallbacks, and overrides. Inspection and feedback are optional; completing the task does not require opening the report. |
| U09 | **Compare enabled and disabled.** Repeat U02 and U05 with Rippletide enabled and disabled, starting fresh sessions from identical project snapshots. | Both runs are judged against the same task outcome. Capture total time, token usage where available, failed/unnecessary calls, and user interventions. Disabled runs contain no Rippletide decisions. |

For every run, retain the prompt, project starting state, enabled capabilities/preferences, Codex session reference, routing decisions, subsequent tool/agent calls, final artifact or answer, acceptance result, and any human interventions. Link calls to `decision_id` where possible; manually correlate the session and trace when needed. Distinguish a recommendation that was followed, a Codex override, a fallback, and a routing call that never occurred.

Count a required human intervention as an unplanned message or action needed to unblock or correct the task: choosing a tool/agent, reminding Codex to use Rippletide, correcting a wrong decision, supplying missing clarification, or manually recovering/retrying a stalled workflow. Record each event and its cause. Track initial setup, the initial task prompt, planned follow-up tasks, normal permission approvals, and optional inspection/feedback separately. A correction needed for task success still counts even if the tester volunteers it. Report total user interactions alongside this narrower intervention measure.

The suite must demonstrate at least one real Qwen-selected decision followed by execution in each category: native tool, connected MCP tool, and callable agent. Include unresolved choices with multiple plausible candidates so rule-only successes cannot hide a broken model integration. Record skipped eligible routing decisions as failures of the plugin workflow, even when Codex independently completes the task.

## 7. Evaluation and success criteria

### Paired user-test evidence

Every paired report distinguishes **tool-choice correctness**, **invocation
success**, **task correctness**, and **routing compliance**. A passing final fix
does not certify earlier choices; Codex-alone is not the answer key. Judge the
choice against the information available before that call, allowing multiple
appropriate tools. Record correct/incorrect/uncertain/ungradable with evidence and
grade coverage. Keep first-choice errors even when autonomously corrected.

Fixture labels are approved acceptable-route sets kept outside the presented
workspace. For arbitrary tasks, a separate read-only post-run Codex judge applies
one frozen rubric to anonymized traces from both arms. Automated grades are
provisional, not human-approved benchmark labels. Audit corrections append a new
record without replacing original grades. Do not request hidden reasoning or use
later outcomes as evidence that an earlier choice was justified. Judge model,
rubric version, time, and tokens are recorded separately. Post-run grading is not
a human intervention in execution.

Preserve the delegated context, actual route source/model, host call identity,
results, and unknown correlations. Baseline traces show actual tool choices, not
invented internal reasoning. Report setup, execution, grading, cold/warm model
timings, and parent/child token categories separately. Use private local raw logs
and escaped/redacted offline HTML/Markdown/JSON presentation exports. No automatic
upload. Cost estimates require actual pricing; tokens alone are not money.

Parallel paired sessions are the demo default. Repeated sequential trials with
alternating order are available for cleaner performance comparisons. Every new
model comparison uses a fresh pair; do not load all local models concurrently.
Independent checks are identical across arms; missing checks mean ungraded, not
successful. External provider access remains read-only by default.

### Full benchmark targets

All thresholds below are proposed MVP targets, not measured results. Freeze them and the reference hardware before the final evaluation.

Compare four variants: **A** Codex alone; **B** Codex with clear routing instructions; **C** Codex with a rules-only router and Codex fallback; **D** Codex with rules plus the required Qwen backend.

Use at least 200 held-out labeled decisions and 40 complete tasks across at least five repositories. Keep tuning repositories separate. Labels specify all acceptable routes and cases requiring fallback. Run each complete task three times per variant with the same Codex settings, repository starting state, available tools, and acceptance tests; randomize run order. Report variability and failures, not only averages.

| Measure | MVP target |
| --- | --- |
| Contract and preference correctness | 100% of responses validate; no unavailable/disallowed selections; all explicit-preference tests pass. |
| User acceptance and autonomy | U01–U09 meet their acceptance conditions in real sessions. Each capability category has a verified Qwen decision followed by execution. Successful normal-path runs require no manual router invocation, route selection, or extra routing approval; record setup, normal permissions, and deliberate feedback separately. |
| Low human intervention | At least 90% of eligible task runs complete successfully with zero required human interventions. Average at most 0.2 required interventions per attempted run, and no increase versus Codex alone on the same tasks. Measure across U01–U05 and the normal-operation benchmark tasks; define this cohort before testing and report deliberate failure/feedback scenarios separately. |
| Decision quality | At least 90% of selected routes match a human-approved label, with selection on at least 80% of answerable held-out requests. Report model-only accuracy and all fallbacks separately. |
| Model contribution | D selects at least 10 percentage points more answerable requests than C, while maintaining the decision-quality target. This tests whether Qwen adds value beyond rules. |
| Repeatability | At least 99% agreement with each packet's modal decision across 10 runs of 100 fixed packets. Report ties and rule/model results separately. |
| Router latency | Warm request p95 at most 500 ms, including context preparation and inference, on the declared Apple Silicon reference machine. Report cold startup separately; enforce the two-second deadline. |
| Complete-task quality | D's observed task-success rate is at least A's and the strongest B/C baseline's rate. Success is determined by independent task acceptance tests. |
| Time and token savings | D reduces median complete-task time and mean Codex tokens per completed task by at least 10% versus A. Include failed attempts, routing requests, retries, fallbacks, and all reported token categories; report results against B/C as well. |

For time comparisons, use tasks completed by both variants and publish completion rates alongside them. Tokens per completed task equals all tokens spent in an evaluation variant, including failures, divided by completed tasks. Also report cached-token usage and estimated billed cost when available, plus local inference time and memory; token reductions alone do not establish monetary savings. Claims remain provisional when run-to-run uncertainty could erase the observed gain.

For the intervention criterion, divide successful runs with zero required interventions by all attempted runs in the predefined cohort. Include failed, stalled, and abandoned runs in that denominator; silent failure does not count as autonomous success. Report intervention counts and completion rates for A–D using the same definitions and permission settings.

Engineering completion and product success are separate decisions: a working plugin can miss the performance targets. If D offers no useful improvement over B/C, document that result before expanding scope or investing in training.

## 8. Definition of done

- [ ] Plugin installs and completes the documented setup on the declared Codex/macOS configuration.
- [ ] The exact requested Hugging Face backend performs real inference; engine and weight revisions and startup behavior are recorded.
- [ ] All three routes work in the evaluation environment; availability filtering, preferences, and fallback behavior are implemented.
- [ ] Codex completes the request → recommendation → argument generation → execution flow, including override and failure paths.
- [ ] T01–T14 pass their functional assertions; repeatability/performance measurements are reported against their targets.
- [ ] U01–U09 have been exercised by a tester in actual Codex sessions, with evidence and pass/fail results. Native-tool, MCP-tool, and agent handoffs are verified with the required Qwen backend; no missing integration is marked as passed.
- [ ] The evaluation report includes required-intervention counts, total user interactions, successful completion without intervention, and a comparison with Codex alone against the low-human-intervention targets.
- [ ] Local traces and an on-request report show actual decisions and timings; unavailable usage/outcome data is identified.
- [ ] The four-variant evaluation is reproducible, with fixtures, labels, settings, raw results, and a report showing pass/fail against every success criterion.
- [ ] Installation, configuration, supported tools, limitations, disable/uninstall steps, and data locations are documented.
- [ ] The paired runner supports ordinary existing-project tasks and the new-project fixture in separate fresh worktrees, retaining failures and original checkout changes.
- [ ] Tool-choice correctness is reported for both arms with grade provenance, evaluated coverage, unknowns, and append-only audits; judge costs are separate.
- [ ] The current default and three opt-in MLX models perform real pinned inference, with startup/reuse/timeout/identity evidence.
- [ ] Covered native/MCP/agent hook behavior is verified on the pinned local Codex host; missing support blocks preflight, and runtime omissions invalidate routing acceptance.

The MVP is engineering-complete when this checklist is satisfied. It is product-validated only when the success criteria are also met.

## 9. Delivery sequence

1. **Integration proof:** verify the requested model artifacts and one full Codex routing handoff; select the semantic integration, pilot MCP servers and callable agents, and reference hardware.
2. **Functional MVP:** add the three search routes, bounded pilot capability registrations, rules, model selection, preferences, fallback, and traces; pass functional tests.
3. **Evaluation:** run the real-session user acceptance suite, freeze benchmark datasets and settings, run A–D, and publish results against the targets.
4. **Next decision:** expand only where results support it. Fine-tuning on reviewed corrections and RL remain later work.
