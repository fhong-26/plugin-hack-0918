# Answer-aware quality and method review — round 1

**Decision: SATISFIED.** No required fixes remain under the frozen GOAL.md for the fingerprint set below. This accepts the dataset as a 50-case synthetic development pilot of conditional tool choice. It is not a performance evaluation, independent human validation, or a claim about successful tool execution.

Reviewed 2026-09-18 by the independently delegated answer-aware quality/method reviewer. I read GOAL.md first, then all 50 requests, contexts, answer rationales, and listed nearest alternatives. I reviewed every selected tool's full live description/declaration, family membership, host-policy excerpts, manifest, README, and validator. I did not execute scenario actions, authenticate connectors, or modify the dataset or plugin.

## Reviewed fingerprints

All hashes below were recomputed from `work/benchmark-real-codex-50/round-1/` and agree with its manifest. Acceptance applies to this exact set.

| File | SHA-256 |
| --- | --- |
| GOAL.md | `939730eb260c799cb2cef015d87f82dc2c53eb738c1b477e9fd06c1237adb5f3` |
| tasks.jsonl | `77b26581dc3373576de6e88edd8100bc40d601b8fee8e096945c13cbea976e2a` |
| answers.jsonl | `cda1db2b5d121d58f05e81deebf260e17920a58358ad0aff49921a2ec2c17802` |
| runtime-tools.json | `0e47488e3f401176aa2e370d1b6aaaa494a436e382d1672169828d9d72ddcff9` |
| families.json | `cd3363f7e88aec04b35b0bc4f3fa6458ea4fb17f75f563fa55b7b37e6b587a61` |
| host-policy.json | `f21bf1d1081f54bcf4099fff8697c2844d39532cd914220bf256c0862c85610d` |

## Required fixes

None. All 50 labels are acceptable as the single best next tool under the supplied context and visible contracts/policy.

## Provenance, candidate coverage, and method

- I independently compared the snapshot against this reviewer's live `ALL_TOOLS`. All 60 selected tools have exactly matching callable names and description strings, including the embedded declarations. The snapshot's complete 192-name exposure list also matches the live list, with no additions or omissions. This establishes metadata fidelity and exposure only; it does not establish authenticated access, permissions, or service health.
- Each family has ten cases and fixed candidate membership, including `exec_command`: 7 local, 19 Codex, 14 Linear, 12 Slack, and 14 Notion candidates. I inspected omitted exposed tools for direct competitors. I found no omitted equally suitable direct competitor that is needed to resolve one of these cases fairly. For example, Slack's omitted user-channel listing lacks the requested description search; Linear's omitted exact attachment lookup needs an attachment ID not yet known in LIN-01; task automation is not the active-session wait requested in CDX-10. General JavaScript execution is another broad programming route, but does not displace the dedicated local-image/UI/session operations or make arbitrary shell operations separate labels.
- Broad capabilities are preserved. `exec_command` correctly covers source searching, Git inspection, test launch, and text-file reading. Linear listings retain content, branch-name, and other extensive fields; exact reads are distinguished by known identity or requested fields rather than an invented “list tools only return IDs” restriction. Slack's file reader remains capable of reading Canvas Markdown. Notion's single-source query tool remains capable of SQL and multi-source inputs; NOT-09 is distinguished by faithful rich text, not an invented inability to execute SQL.
- The supplied host-policy strings are genuine excerpts of this session's instructions. Policy-based preference for persisted Linear, Slack, and Notion MCP routes is explicitly explained in the relevant answer rationales. The shell alternative is not artificially disabled.
- The complete catalog is deliberately not evaluated: these are legitimate family-conditioned subsets. The README accurately excludes family routing, arguments, execution, enforcement, and complete task quality. Scenario connectivity and prior results are fictional context, not claims about live service health.
- I ran `validate.py`: PASS, 50 cases, 60 real candidate tools, 46 distinct gold tools. These are package counts, not accuracy results. I also independently confirmed that every readable case's request, context, rationale, label, and alternative explanation matches its JSON source; no rendering differences were found.
- I independently recomputed all 50 candidate orders from the stated SHA-256 case-ID seed and family order; all match. This computation did not use answer labels.
- Chooser input is limited to request, context, host instructions, and exact tools. IDs, family/scenario-group metadata, gold labels, rationale, and reviewer notes stay outside `input`. The necessary references to previous tool sessions and connection access are legitimate decision-point state. I found no human-authored answer-name injection or future-result leakage.
- The visible prerequisites support each next action: known session IDs, project IDs, page/diff/document identifiers, completed schema/access reads, explicit authorization for private Slack search, and elapsed async polling backoff. Necessary identities are not left for the chooser to invent. Requests requiring later summarization or pagination still have one unambiguous first next tool; the goal does not require a single call to finish every user task.

## Case-by-case disposition

The table records the deciding distinction. All nearest alternatives in the answer key were checked against their full contracts, not only the selected comparison named here.

| Case | Accepted tool | Deciding distinction |
| --- | --- | --- |
| LOC-01 | `exec_command` | Local source search is a shell operation; no edit or active session exists. |
| LOC-02 | `exec_command` | The unread unstaged patch must be inspected; opening a review panel does not retrieve it for analysis. |
| LOC-03 | `exec_command` | The known focused test has not started, so there is no session to poll. |
| LOC-04 | `write_stdin` | An active unified execution session and its ID are already supplied. |
| LOC-05 | `write_stdin` | The authorized selection must be sent to the existing PTY prompt. |
| LOC-06 | `view_image` | A known local image needs pixel inspection; the dedicated tool explicitly covers this. |
| LOC-07 | `mcp__codex_app__open_in_codex` | The user specifically requests right-panel display of the already inspected file. |
| LOC-08 | `mcp__codex_app__read_thread_terminal` | The output belongs to the user-operated app terminal, with no unified session ID. |
| LOC-09 | `mcp__codex_app__load_workspace_dependencies` | Configured bundled runtime paths are unresolved; a system executable lookup is insufficient. |
| LOC-10 | `exec_command` | Read a known local text configuration; no modification or image interpretation is requested. |
| CDX-01 | `mcp__codex_app__list_threads` | Find an unidentified active sidebar task before reading or navigating to its ID. |
| CDX-02 | `mcp__codex_app__read_thread` | The exact completed task is known; its earlier conclusion is missing from the listing summary. |
| CDX-03 | `mcp__codex_app__navigate_to_codex_page` | Switch the main app to a known conversation; a content panel does not perform that navigation. |
| CDX-04 | `mcp__codex_app__list_projects` | Creation's required project-ID/Git-state lookup has not happened. |
| CDX-05 | `mcp__codex_app__create_thread` | The explicit separate-task request and required project listing are already present. |
| CDX-06 | `mcp__codex_app__create_worktree` | Isolate the current repository and attach the checkout to this same task. |
| CDX-07 | `mcp__codex_app__fork_thread` | Copy the completed conversation history into a separate task using the same directory. |
| CDX-08 | `mcp__codex_app__attach_artifact` | The implementation PR exists and still needs the required Codex task attachment. |
| CDX-09 | `mcp__codex_app__remove_artifact` | The known old attachment must be unlinked while preserving the GitHub PR. |
| CDX-10 | `mcp__codex_app__wait_threads` | An active-session completion/attention wait has a known task and cursor. |
| LIN-01 | `mcp__linear__get_issue` | Known issue, with attachments and relations absent from declared issue-list fields. |
| LIN-02 | `mcp__linear__list_issues` | Discover a filtered set; its title and git-branch fields are explicitly supported. |
| LIN-03 | `mcp__linear__get_project` | The project lookup supplies resources plus project-attached customer needs. |
| LIN-04 | `mcp__linear__list_comments` | Read general and anchored project-description discussion, including author and quoted text. |
| LIN-05 | `mcp__linear__list_documents` | Discover matching project documents with updated-time filtering and content fields. |
| LIN-06 | `mcp__linear__get_document` | Read a document already resolved to its exact slug; listing lacks that exact-ID filter. |
| LIN-07 | `mcp__linear__list_diffs` | Discover the user's pending review queue using repository and reviewer filters. |
| LIN-08 | `mcp__linear__get_diff` | Exact selected review slug makes direct lookup preferable to another broad list query. |
| LIN-09 | `mcp__linear__get_diff_threads` | Unresolved discussion filtering and the authenticated user's drafts are explicitly supported. |
| LIN-10 | `mcp__linear__list_issue_statuses` | Enumerate team status definitions, including empty statuses absent from issue samples. |
| SLK-01 | `mcp__slack__slack_read_channel` | Known channel's latest timeline, rather than a selected thread or content search. |
| SLK-02 | `mcp__slack__slack_read_thread` | Known parent channel/timestamp; six unread replies carry the requested discussion. |
| SLK-03 | `mcp__slack__slack_search_channels` | Discover a channel directory record through descriptive terms, not message content. |
| SLK-04 | `mcp__slack__slack_search_public` | Public content search; consent required by catalog policy for the broader search is absent. |
| SLK-05 | `mcp__slack__slack_search_public_and_private` | Explicit prior-question/current-reply consent; location may be an unknown private channel or DM. |
| SLK-06 | `mcp__slack__slack_read_file` | Known accessible 64-KB text attachment is below the documented limit; body is unread. |
| SLK-07 | `mcp__slack__slack_read_canvas` | The section-ID mapping is required; ordinary file Markdown is not the requested structural result. |
| SLK-08 | `mcp__slack__slack_search_users` | Discover workspace people by profile role, with no known individual or selected channel. |
| SLK-09 | `mcp__slack__slack_read_user_profile` | Read timezone/status for a resolved identity; user-search contract directs detailed lookup here. |
| SLK-10 | `mcp__slack__slack_list_channel_members` | Retrieve actual channel membership, including bots, rather than infer it from message authors. |
| NOT-01 | `mcp__notion__notion_fetch` | Known page URL, unread page body, and completed enhanced-Markdown specification read. |
| NOT-02 | `mcp__notion__notion_search` | Current access explicitly reports AI search unavailable; short keywords need no restricted options. |
| NOT-03 | `mcp__notion__notion_get_comments` | Known page and anchored ordinary discussion; page indicators do not contain full replies. |
| NOT-04 | `mcp__notion__notion_get_users` | Continue an unfiltered roster using the provided pagination cursor and account types. |
| NOT-05 | `mcp__notion__notion_list_recent_pages` | Recover repeated viewing history without title clues; edit time is not viewing history. |
| NOT-06 | `mcp__notion__notion_list_favorite_pages` | Retrieve the user's favorite collection in native sidebar order. |
| NOT-07 | `mcp__notion__notion_ai_search` | Current access says available; the actual contract requires this for title/keyword searches too. |
| NOT-08 | `mcp__notion__notion_get_tool_access` | Both search contracts require access discovery before choosing a first content-search route. |
| NOT-09 | `mcp__notion__notion_query_data_sources` | Schema/access known; faithful rows preserve rich-text mentions and links, unlike SQL text. |
| NOT-10 | `mcp__notion__notion_get_async_task` | Known async handle and elapsed backoff; operation status/result is distinct from page discovery. |

## Optional improvements, not acceptance conditions

- CDX-07 could say “All preceding turns are complete” instead of “The current task is idle; all turns and their responses are complete.” An assistant making the fork call is handling a new turn, so the former is more literal. This does not change the intended completed-history fork or its unique best label.
- The structural validator could additionally assert manifest summary counts and deterministic candidate ordering. I independently checked both in this review; their absence from the small validator is not a dataset defect.

The separate blind reviewer still needs to accept these same fingerprints for the overall two-reviewer stopping rule to be met.
