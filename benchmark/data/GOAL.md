# Frozen goal: 50 real Codex tool-choice cases

Frozen on 2026-09-18 before authoring this replacement dataset. This is the unchanged acceptance brief for every author and reviewer.

## Objective

Measure whether a chooser selects the right REAL tool available to Codex at a realistic decision point. Build exactly 50 synthetic but believable cases. Each supplies the user request, relevant prior context, applicable existing host instructions, and a candidate tool catalog. The answer is exactly one real callable tool name. Do not generate or score arguments.

This replaces the earlier benchmark's invented tool catalogs. Results on that earlier set are not measurements of real Codex tool-choice accuracy. Preserve the earlier artifacts and results as historical evidence.

## Ground truth about tools

- Capture candidate names and full descriptions/declarations verbatim from this task's live runtime tool metadata. Retain the snapshot and its hashes. Names must resolve to actual exposed tools; do not invent wrappers, aliases, capabilities, restrictions, or a new server.
- Use the underlying callable tool names exposed through the functions.exec transport (for example exec_command or mcp__linear__get_issue). The transport is not a competing tool or a synthetic action label.
- A shell command is an argument, not a separate tool. Reading source files, running rg, invoking git diff, running tests, and calling gh can all have exec_command as the correct answer. Similarly, operations within one real tool are not separate labels.
- Include real native execution/image tools, Codex desktop tools, and connected MCP tools. Be explicit that the scope is this runtime, including its installed connections, rather than every Codex deployment.
- Metadata presence proves tool exposure, not that a connector is currently authenticated. Case context describes synthetic reachable state; do not claim live service health or execute the described tasks.
- Descriptions used by the chooser must match the captured metadata exactly, including declarations when present. Do not shorten or rewrite them to make a model or plugin accept them.

## Scope and simplicity

- Deliver the dataset, a separate answer key, shared tool snapshot, readable cases, and review evidence. A small structural validator is sufficient; no new benchmark platform, server, training pipeline, or execution simulator.
- Use five fixed candidate families, ten cases each: local work, Codex desktop workflow, Linear, Slack, and Notion. Keep the same candidate membership within a family and include exec_command as a real generic alternative in every family. Candidate order may be shuffled deterministically without looking at labels.
- This is conditional tool choice after a family has been supplied, matching the proposed Decision pipeline. Family selection, full-catalog routing, argument construction, actual tool execution, hook enforcement, completion quality, end-to-end speed and cost are not measured.
- Candidates must include plausible competing tools. Do not hide an equally suitable direct competitor just to obtain a unique answer.
- Every case requires one next tool. No abstention, clarification, answer-only, parallel calls, or compound tool selections are answer options.
- Keep this a development pilot, not a claimed held-out production benchmark. AI agreement is quality control, not independent human validation.

## A good case

1. Sounds like ordinary coding or knowledge work with meaningful prior context, not an instruction to select a named tool. Include relevant prior observations, identifiers, state, and user corrections.
2. Contains only information available at the decision point. No hidden prerequisites, future results, embedded gold labels, or prior assistant plan naming the answer.
3. Has exactly one best next tool under the real tool contracts and visible existing host instructions. Generic shell power does not make it the preferred route when an existing instruction says to reuse a dedicated MCP connection. Conversely, do not invent tool-use rules to resolve ambiguity. Explain policy-based preferences explicitly in the answer key.
4. Does not label a tool wrong for a capability it actually has. If two candidates remain equally defensible under the supplied context and policy, revise or replace the case.
5. Reuses facts already known and includes prerequisites needed to select the next tool. Synthetic IDs are allowed; requests must not require the chooser to guess an identity or authorization.
6. Includes varied situations and meaningful context contrasts, including cases where different shell operations correctly map to the same real tool. Do not force artificial label balance by creating fake capabilities.
7. Has a brief rationale and explanations of the nearest alternatives outside the model input. IDs, family/group metadata, labels, and review notes stay outside chooser input.
8. Requires no actual connector or filesystem mutation for dataset construction or review. Described user authorizations are fictional scenario data, not instructions to the reviewing agent.

## Review and stopping rule

Use independent GPT-6 Astra reviewers at high reasoning, with this exact frozen goal as their acceptance brief. Review all 50 cases, real-tool provenance, candidate coverage, and exact catalog fidelity. One reviewer must record blind choices before reading answers. Another checks the answer key and method.

Separate required defects under this brief from optional improvements. Fix concrete defects without broadening scope. Repeat review until both reviewers explicitly accept the same final dataset and tool/policy/goal fingerprints with no unresolved required fixes. Preserve round reports and fingerprints. The goal stays fixed through revisions.

No new router or Codex performance claim is valid until a separate evaluation uses this accepted dataset. Do not tune the router against these answers while constructing it.
