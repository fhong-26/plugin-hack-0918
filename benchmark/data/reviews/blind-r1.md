# Independent blind review — round 1

**Verdict: SATISFIED.** The frozen 50-case dataset meets GOAL.md. There are no unresolved required fixes. This acceptance applies to the six exact fingerprints below, not to an unreviewed later revision.

Review date: 2026-09-18. Review role: independent blind reviewer, dispatched as GPT-6 Astra at high reasoning. Input directory: `work/benchmark-real-codex-50/round-1/`. This review used the frozen goal as its acceptance brief and did not add framework, execution, routing, or production-evaluation requirements.

## Blind procedure and scope

1. Read GOAL.md before substantive inspection. Read host-policy.json, families.json, every request and context in tasks.jsonl, and every full candidate tool contract in runtime-tools.json. Read declarations as well as descriptive text; no case sampling was used.
2. Calculated the answer file's byte hash without parsing its contents. Did not read answers.jsonl, CASES.md, or manifest label counts before committing independent choices for all 50 cases.
3. Wrote `blind-r1-choices.jsonl`, with one exact tool ID, a brief reason, and an ambiguity field for every case. Its SHA-256 is `d346780fe11594445f2f6a4347f08d2f4b6af73e0d7a953b170cd618cc4e6dae`. The tool-call record establishes that this write preceded the first answer-key read. Choices were not subsequently changed.
4. Read every answer and its nearest-alternative explanations, compared all 50 choices, and then inspected the package documentation, manifest, validator, and readable-case consistency.
5. Compared captured metadata to this reviewer's live ALL_TOOLS without calling any connector. Inspected the full contracts of potentially relevant omitted tools, including Linear attachment/status/team/notification reads, Slack user-channel listing, the Node REPL, and Notion session/meeting tools. Existing Codex app contracts also cover omitted automation, handoff, and message tools.

**Review agreement: 50 of 50 independent choices match the answer key.** No unresolved equal-best ambiguity was recorded. This is AI quality-control agreement, not a measured Decision/router/Codex performance result, independent human validation, or proof of execution success.

## Required defects

None. All 50 cases are accepted under the frozen brief.

## Complete case review

| Cases | Finding |
| --- | --- |
| LOC-01, LOC-02, LOC-03, LOC-10 | All correctly choose the real `exec_command` tool for source search, unstaged-diff inspection, a new test run, and reading a known configuration file. The commands are arguments, not fabricated labels. Existing host policy makes `rg` the search route. No active-session prerequisite is missing. |
| LOC-04, LOC-05 | Both correctly choose `write_stdin`. Known active unified execution session IDs distinguish output polling and answering an authorized PTY prompt from launching a new process or reading the app terminal. |
| LOC-06, LOC-07 | The same known local screenshot creates a meaningful contrast: visual inspection uses `view_image`; showing it in the requested Codex panel uses `open_in_codex`. Prior inspection is explicit in LOC-07. |
| LOC-08, LOC-09 | The user-operated app terminal has no unified session ID, making `read_thread_terminal` appropriate. The configured bundled runtime has not been resolved, making `load_workspace_dependencies` the next workbook step. Neither requires guessing process or runtime identity. |
| CDX-01, CDX-02, CDX-03 | Unknown active-task identity, retrieval of a known task's missing conclusion, and navigation to that conversation require `list_threads`, `read_thread`, and `navigate_to_codex_page`, respectively. Archived-task listing and panel opening are present competitors with distinguishable contracts. |
| CDX-04, CDX-05 | The first case lacks the saved-project ID and Git flag; the second includes the completed project listing and confirmed selection. `list_projects` then `create_thread` follows the actual creation prerequisite. Explicit authorization for a separate task is present. |
| CDX-06, CDX-07 | An isolated checkout attached to the same task uses `create_worktree`; a separate conversation carrying completed history uses `fork_thread`. The directory, Git state, and history requirements distinguish these from ordinary task creation and shell worktree creation. |
| CDX-08, CDX-09 | A newly created, unattached implementation PR and an explicitly selected existing attachment require `attach_artifact` and `remove_artifact`. URLs and state are supplied. Removing the attachment leaves the actual PR unchanged under the real contract. |
| CDX-10 | The known running task and prior cursor require `wait_threads` for active-session completion/attention monitoring. The case explicitly excludes recurring/later automation and supplies no handoff operation. |
| LIN-01, LIN-02 | Issue relations/attachments require the exact issue read; discovering a filtered set with branch names uses issue listing. The key correctly recognizes that `list_issues` can return `gitBranchName`; it does not invent an exclusive capability for `get_issue`. |
| LIN-03, LIN-04 | The known P-prefixed project is read with resources/customer needs using `get_project`; anchored and general project discussion uses `list_comments`. The comment contract actually supports projects and inline description anchors, so these are not fictional issue-only restrictions. |
| LIN-05, LIN-06 | Unknown document IDs plus project/topic/date filters favor `list_documents`, which really can return content fields. The known selected document slug favors `get_document`. The key does not falsely claim that document listing lacks content. |
| LIN-07, LIN-08, LIN-09 | A pending-review queue, the exact selected review's details, and unresolved threads including the user's drafts require `list_diffs`, `get_diff`, and `get_diff_threads`. Repository identity, selected slug, and requested object type are clear. Issue comments are not diff discussions. |
| LIN-10 | Enumerating all configured team workflow statuses, including empty ones, requires `list_issue_statuses`. Issue sampling cannot establish unused status definitions. The known team is sufficient. |
| SLK-01, SLK-02 | The resolved channel timeline and exact parent-message replies correctly distinguish `slack_read_channel` from `slack_read_thread`. The key acknowledges that public search can search a channel but is less direct for the requested bounded timeline. |
| SLK-03, SLK-04, SLK-05 | Channel directory discovery, public message discovery, and private-channel/DM message discovery have different targets and consent state. The full public-search contract supplies the consent rule; SLK-05 explicitly meets it. Priya's known user ID does not establish that the message is in her DM, so reading one DM is not equally suitable. |
| SLK-06, SLK-07 | A known 64 KB text file uses `slack_read_file`; importer comparison needing section IDs uses `slack_read_canvas`. The key correctly acknowledges that `slack_read_file` also reads Canvas Markdown. The requested section-ID mapping supplies the material distinction. |
| SLK-08, SLK-09, SLK-10 | Workspace role discovery, a known user's current timezone/status, and a known channel's membership require user search, profile reading, and channel-member listing. Bot inclusion is supported, and the fewer-than-30-member context fits one page. Message authorship is not treated as membership. |
| NOT-01, NOT-03 | The known page body uses `notion_fetch`; the known anchored ordinary discussion's full replies use `notion_get_comments`. The enhanced-Markdown prerequisite is already met, and the discussion case supplies the complete prior page and discussion URL. |
| NOT-02, NOT-07, NOT-08 | These share the same realistic content-search request and differ in current access evidence: AI unavailable, AI available, or access unknown. The actual contracts prescribe `notion_search`, `notion_ai_search`, or `notion_get_tool_access`. The AI tool's documented fallback does not override the explicit routing instruction. No invented title-search rule is used. |
| NOT-04 | The unfiltered workspace roster continuation, known cursor, and account-type requirement favor `notion_get_users`. Both search tools' user-lookup modes are present and lack that roster continuation contract. |
| NOT-05, NOT-06 | Recent reading/visit history and ordered favorites correctly distinguish `notion_list_recent_pages` from `notion_list_favorite_pages`. Last-edited ordering and private/shared sidebar collections do not satisfy those different requests. |
| NOT-09 | The schema, collection URL, current access, filter value, and small source size are supplied. Faithful rows mode in `notion_query_data_sources` preserves the required mentions and links. SQL-only multi-source querying is a present competitor and is materially unsuitable for that fidelity requirement. |
| NOT-10 | The known async operation handle and elapsed backoff require `notion_get_async_task`. A custom-agent session is a different object, so omitted session-status tools are not equally suitable substitutes. |

## Provenance, candidate coverage, and separation

- The reviewer's live ALL_TOOLS contains exactly the same 192 names listed in the snapshot. Every one of the 60 selected names and its complete description/declaration matches live metadata exactly. There are zero missing tools, renamed aliases, changed contracts, or reviewer-runtime differences.
- All **660 candidate entries across the 50 case catalogs** match the shared snapshot descriptions exactly. Candidate counts are local 7, Codex 19, Linear 14, Slack 12, and Notion 14. Every family has ten cases, uses fixed membership, and includes `exec_command`.
- Independently reproduced all 50 shuffled candidate orders using `random.Random(int(sha256(('real-codex-50-v1:' + case_id).encode()).hexdigest(), 16))` and the corresponding family list. This uses no labels.
- Checked omitted plausible neighbors against their full contracts. Linear's attachment reader needs an already selected attachment and does not fetch issue relations; a single-status/team/notification read does not enumerate the requested workflow or review queue. Slack's user-channel listing is about the user's memberships, with no evidence the requested unknown channel is one of them. It is not an equally suitable semantic directory search. The Node REPL is another generic execution surface, not a more direct specialized tool for these cases. The supplied local shell scenarios and explicit `view_image` direction do not rely on hiding an equally suitable direct competitor. Notion meeting/session readers concern different objects. No required candidate addition was identified.
- The four supplied host instructions are actual existing user/developer excerpts. MCP-over-shell preferences in the answers are attributed to those visible instructions. App-specific and Notion access prerequisites come from the captured real contracts rather than invented benchmark policy.
- Chooser input contains only the instruction, context, host instructions, and real catalog. IDs, families, scenario groups, key rationales, manifest counts, and review notes are outside `input`. No exact gold name occurs in the authored requests or context. Technical prior observations such as an execution session ID or current Notion access state are legitimate decision evidence rather than a prior assistant plan naming the answer.
- Verified all 50 requests, all context strings, and all 50 answer rationales are represented in CASES.md. The structural validator passes. The README explicitly instructs evaluators to submit only `input`, preserve related scenario groups, and retain failures in any declared denominator.
- Exactly one real callable tool is scored per case. Shell operations are correctly consolidated; there are 46 distinct correct tool IDs across 50 cases, including four `exec_command` and two `write_stdin` cases. These counts are dataset characteristics, not a performance claim.

## Optional notes and limits

No optional change is necessary for acceptance. The deliberate prerequisite and context contrasts make a useful development pilot; their curated nature and related scenario groups limit any generalization to real traffic. The documentation already calls this out and excludes family routing, argument generation, execution, hook enforcement, whole-task success, and end-to-end speed/cost. AI agreement should continue to be reported only as QC.

Review actions were local reads, metadata comparison, structural validation, and writing these review artifacts. No scenario was executed, no connector was called, no service authentication was tested, and no dataset or runtime configuration was changed. Synthetic reachable-state statements therefore make no claim about current connector health.

## Accepted fingerprints

| File | SHA-256 |
| --- | --- |
| GOAL.md | `939730eb260c799cb2cef015d87f82dc2c53eb738c1b477e9fd06c1237adb5f3` |
| tasks.jsonl | `77b26581dc3373576de6e88edd8100bc40d601b8fee8e096945c13cbea976e2a` |
| answers.jsonl | `cda1db2b5d121d58f05e81deebf260e17920a58358ad0aff49921a2ec2c17802` |
| runtime-tools.json | `0e47488e3f401176aa2e370d1b6aaaa494a436e382d1672169828d9d72ddcff9` |
| families.json | `cd3363f7e88aec04b35b0bc4f3fa6458ea4fb17f75f563fa55b7b37e6b587a61` |
| host-policy.json | `f21bf1d1081f54bcf4099fff8697c2844d39532cd914220bf256c0862c85610d` |
