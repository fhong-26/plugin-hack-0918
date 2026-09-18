# 50 cases using real Codex tools

Human review rendering, including answers. Never send this file to a chooser.

The model receives only each tasks.jsonl record's `input`: request, context, existing host instructions, and real tool definitions. All tool descriptions and declarations are copied verbatim into that input. The fixed candidate sets below are family subsets of this runtime; this does not test family selection.

## Existing host instructions

- Reuse the user's persisted connections before proposing new authentication. Preferred existing routes are Linear, Notion, and Slack through their global MCP servers; GitHub through `gh`; Railway through `railway`; and Azure through `az`.
- For Notion URLs or requests about Notion content, use the Notion MCP tools first, especially `notion-fetch` and `notion-search`.
- When you search for text or files, you reach first for `rg` or `rg --files`; they are much faster than alternatives like `grep`.
- Do not use tools to send messages to others (e.g. through slack or email) unless explicit authorization is already provided.

## local candidate catalog

- `exec_command`
- `write_stdin`
- `view_image`
- `apply_patch`
- `mcp__codex_app__read_thread_terminal`
- `mcp__codex_app__open_in_codex`
- `mcp__codex_app__load_workspace_dependencies`

## codex candidate catalog

- `exec_command`
- `mcp__codex_app__list_threads`
- `mcp__codex_app__list_archived_threads`
- `mcp__codex_app__read_thread`
- `mcp__codex_app__navigate_to_codex_page`
- `mcp__codex_app__open_in_codex`
- `mcp__codex_app__list_projects`
- `mcp__codex_app__create_thread`
- `mcp__codex_app__create_worktree`
- `mcp__codex_app__fork_thread`
- `mcp__codex_app__read_thread_terminal`
- `mcp__codex_app__list_artifacts`
- `mcp__codex_app__attach_artifact`
- `mcp__codex_app__remove_artifact`
- `mcp__codex_app__set_thread_title`
- `mcp__codex_app__set_thread_pinned`
- `mcp__codex_app__set_thread_archived`
- `mcp__codex_app__wait_threads`
- `mcp__codex_app__get_handoff_status`

## linear candidate catalog

- `exec_command`
- `mcp__linear__get_issue`
- `mcp__linear__list_issues`
- `mcp__linear__list_comments`
- `mcp__linear__get_project`
- `mcp__linear__list_projects`
- `mcp__linear__get_document`
- `mcp__linear__list_documents`
- `mcp__linear__get_diff`
- `mcp__linear__list_diffs`
- `mcp__linear__get_diff_threads`
- `mcp__linear__list_issue_statuses`
- `mcp__linear__list_milestones`
- `mcp__linear__get_milestone`

## slack candidate catalog

- `exec_command`
- `mcp__slack__slack_read_channel`
- `mcp__slack__slack_read_thread`
- `mcp__slack__slack_read_file`
- `mcp__slack__slack_read_canvas`
- `mcp__slack__slack_search_public`
- `mcp__slack__slack_search_public_and_private`
- `mcp__slack__slack_search_channels`
- `mcp__slack__slack_search_users`
- `mcp__slack__slack_read_user_profile`
- `mcp__slack__slack_get_reactions`
- `mcp__slack__slack_list_channel_members`

## notion candidate catalog

- `exec_command`
- `mcp__notion__notion_fetch`
- `mcp__notion__notion_search`
- `mcp__notion__notion_get_comments`
- `mcp__notion__notion_get_users`
- `mcp__notion__notion_list_recent_pages`
- `mcp__notion__notion_list_favorite_pages`
- `mcp__notion__notion_list_private_pages`
- `mcp__notion__notion_list_shared_pages`
- `mcp__notion__notion_query_data_sources`
- `mcp__notion__notion_query_multiple_data_sources`
- `mcp__notion__notion_get_async_task`
- `mcp__notion__notion_ai_search`
- `mcp__notion__notion_get_tool_access`

## LOC-01

**Family:** local; **scenario group:** local-source-search

**Request:** The nightly import still retries after a 429. Find where the retry delay is calculated before we change it.

**Context:**

- The checkout is /workspace/invoice-worker. The relevant code is local and has not yet been inspected.
- The last completed command showed a clean working tree and directories src/, tests/, and scripts/. No command session is active.

**Answer:** `exec_command`

Search the local source, using rg under the existing host policy. The search expression and working directory are arguments to exec_command, not distinct tools.

**Nearest alternatives:**

- `apply_patch`: No responsible edit is possible until the implementation is located.
- `mcp__codex_app__open_in_codex`: Opening a panel does not inspect or search its contents.
- `write_stdin`: There is no active command session to continue.

## LOC-02

**Family:** local; **scenario group:** local-git-inspection

**Request:** Before committing, tell me whether my unstaged change to the timeout handler could explain the regression.

**Context:**

- The repository is /workspace/invoice-worker. A completed git status reported one modified file, src/retry.ts.
- The file's current contents and the unstaged patch have not been read. No command is running.
- The user wants analysis before any edits or commits.

**Answer:** `exec_command`

Inspect the local unstaged diff through the shell. git diff is an argument to the real exec_command tool.

**Nearest alternatives:**

- `apply_patch`: The request is to inspect the existing change, not change the file.
- `mcp__codex_app__open_in_codex`: Showing a review panel to the user does not give the assistant the patch for analysis.
- `write_stdin`: The status command has already exited.

## LOC-03

**Family:** local; **scenario group:** test-start-versus-poll

**Request:** The parser fix is saved. Run its focused regression test and tell me whether it passes.

**Context:**

- The local repository is /workspace/receipt-parser. Earlier inspection confirmed package.json has a test:parser script that runs the relevant unit tests offline.
- The edit is complete. No test has run since the edit, and there is no active execution session.

**Answer:** `exec_command`

Start the existing focused test command. Tests are shell-command parameters, not a fictional ci.run_test tool.

**Nearest alternatives:**

- `write_stdin`: There is no existing test session to poll.
- `apply_patch`: The fix is already saved; validation is the next step.
- `mcp__codex_app__read_thread_terminal`: The test has not started in the app terminal.

## LOC-04

**Family:** local; **scenario group:** test-start-versus-poll

**Request:** Has that parser regression test finished? Give me its result when it does.

**Context:**

- The focused regression command was already launched through exec_command in /workspace/receipt-parser.
- The latest tool result contains session_id: 7142 and output 'Running parser regression suite…', with no exit_code. That session remains active.
- No later result has been collected.

**Answer:** `write_stdin`

Collect more output from the known active unified exec session. Empty input polls it without starting another test run.

**Nearest alternatives:**

- `exec_command`: Starting a new command would not retrieve the retained output and exit state of session 7142.
- `mcp__codex_app__read_thread_terminal`: This is a unified exec session, not the user-operated app terminal.
- `apply_patch`: No failure requiring another edit has been reported.

## LOC-05

**Family:** local; **scenario group:** interactive-local-session

**Request:** Use the demo configuration we prepared and continue the local setup.

**Context:**

- The local setup script is already running in a PTY created by exec_command; its active session_id is 8391.
- The script is paused at 'Configuration [demo/minimal]:'. The user has now chosen demo.
- The script writes only the disposable sandbox under /workspace/scratch-demo. This setup was requested by the user, and no further question is pending.

**Answer:** `write_stdin`

Send the user's selected input to the waiting PTY session. The answer text is a parameter, not another tool choice.

**Nearest alternatives:**

- `exec_command`: A fresh shell process would not answer the prompt in the existing PTY.
- `mcp__codex_app__read_thread_terminal`: The prompt and session are already known; reading the app terminal will not send input to this PTY.
- `apply_patch`: The script expects interactive input rather than a file patch.

## LOC-06

**Family:** local; **scenario group:** inspect-versus-show-image

**Request:** Does this screenshot show the checkout button overlapping the total on mobile?

**Context:**

- The screenshot was produced by a completed local browser test and is saved at /workspace/storefront/artifacts/cart-mobile.png.
- The file is present on disk, but the assistant has not viewed its pixels. The test log reports no layout metrics.

**Answer:** `view_image`

Load the local image for visual inspection, as the tool's real description explicitly directs.

**Nearest alternatives:**

- `mcp__codex_app__open_in_codex`: Opening a panel shows the user a file but does not inspect its image pixels for the assistant.
- `exec_command`: A shell listing or file read does not supply the visual evidence needed to judge overlap.
- `apply_patch`: The visual problem has not yet been assessed.

## LOC-07

**Family:** local; **scenario group:** inspect-versus-show-image

**Request:** Put the mobile screenshot in the right-hand Codex panel so I can compare it with the design.

**Context:**

- The assistant already inspected /workspace/storefront/artifacts/cart-mobile.png and described the overlapping checkout button.
- The screenshot is still on disk. The user now wants to see that file in the current task's UI; no further image analysis is requested.

**Answer:** `mcp__codex_app__open_in_codex`

The requested action is to display a known workspace file in a Codex panel. The real tool explicitly handles this UI action.

**Nearest alternatives:**

- `view_image`: The assistant has already inspected the image; that tool does not satisfy the user's requested panel placement.
- `exec_command`: The existing Codex UI tool directly opens the specified file in the requested panel.
- `mcp__codex_app__read_thread_terminal`: The requested surface is the screenshot, not terminal output.

## LOC-08

**Family:** local; **scenario group:** app-terminal-versus-exec-session

**Request:** I ran the migration in this task's terminal. Read what it printed before deciding what to do next.

**Context:**

- The user typed the command in the current desktop task's app terminal, outside assistant tool execution.
- No exec_command session_id exists for that process. Its output has not yet been read by the assistant.
- The user is asking to inspect the existing output, not rerun the migration.

**Answer:** `mcp__codex_app__read_thread_terminal`

Read the current app terminal output using its dedicated tool. It takes no session ID and is explicitly intended for this decision point.

**Nearest alternatives:**

- `write_stdin`: There is no unified exec session ID to address.
- `exec_command`: A new shell command does not read the retained app terminal screen and could rerun the migration.
- `mcp__codex_app__open_in_codex`: Opening the terminal panel does not return its contents for analysis.

## LOC-09

**Family:** local; **scenario group:** bundled-artifact-runtime

**Request:** Build the workbook using the Python and spreadsheet libraries bundled with this desktop task.

**Context:**

- The requested workbook layout and source CSV are already specified, and the spreadsheet skill has already been read.
- The current task has not resolved the configured bundled runtime paths. No Python script has started.
- The user specifically wants the bundled runtime; the system Python location would not establish which runtime Codex configured.

**Answer:** `mcp__codex_app__load_workspace_dependencies`

Resolve the task's configured bundled dependency paths using the real discovery tool before running the workbook script.

**Nearest alternatives:**

- `exec_command`: Looking up an arbitrary Python executable would not establish the configured bundled workspace dependency paths; the dedicated tool returns those paths.
- `write_stdin`: There is no running workbook process.
- `mcp__codex_app__open_in_codex`: The output workbook has not been created.

## LOC-10

**Family:** local; **scenario group:** local-config-read

**Request:** Check the retry limit currently configured for the worker; I don't remember whether we left it at three or five.

**Context:**

- The repository configuration is /workspace/invoice-worker/config/worker.toml. Its path is known from the README, but its contents have not been read.
- No command is running. The user asks only for the local configured value, not a remote service setting or a change.

**Answer:** `exec_command`

Read the known local text file using a shell command. File reading is an exec_command operation in this runtime.

**Nearest alternatives:**

- `mcp__codex_app__open_in_codex`: Opening the file for the user does not retrieve its text for the assistant's answer.
- `apply_patch`: The user requested the current value, not a modification.
- `view_image`: This is a text configuration file, not an image requiring visual inspection.

## CDX-01

**Family:** codex; **scenario group:** find-versus-read-task

**Request:** Find the Codex task where we investigated duplicate webhook deliveries yesterday.

**Context:**

- The user says the task is still in the active sidebar, but cannot recall its title.
- The current conversation has no thread ID or earlier task listing. The repository has several unrelated webhook branches.
- The request is to identify the existing task first.

**Answer:** `mcp__codex_app__list_threads`

List active app tasks and their retrieval summaries to locate the unknown task ID.

**Nearest alternatives:**

- `mcp__codex_app__read_thread`: It requires the target thread ID, which is unknown.
- `mcp__codex_app__list_archived_threads`: The user identified an active task, not an archived one.
- `mcp__codex_app__navigate_to_codex_page`: Navigation also needs the unknown target ID.
- `exec_command`: Searching repository branches cannot identify the corresponding Codex sidebar task.

## CDX-02

**Family:** codex; **scenario group:** find-versus-read-task

**Request:** What conclusion did we reach about duplicate webhook deliveries in that task?

**Context:**

- A previous app listing identified the completed task titled 'Investigate webhook duplicates', threadId '01a11111-2222-7333-8444-555555555555', hostId 'local'.
- Its short listing summary only says that an investigation was performed; it does not include the conclusion.
- The user wants the earlier findings here, while staying in the current task.

**Answer:** `mcp__codex_app__read_thread`

Read the known completed task's turn summaries and outputs for the missing conclusion.

**Nearest alternatives:**

- `mcp__codex_app__list_threads`: The identity is already known and the listing summary lacks the conclusion.
- `mcp__codex_app__navigate_to_codex_page`: The user wants the findings in this task rather than a UI switch.
- `mcp__codex_app__wait_threads`: This is retrieval of earlier findings from a completed task, not waiting for active work.
- `exec_command`: Repository history does not contain the conversation's conclusion.

## CDX-03

**Family:** codex; **scenario group:** read-versus-open-task

**Request:** Take me to 'Investigate webhook duplicates' so I can read the conversation myself.

**Context:**

- The exact task is already resolved: threadId '01a11111-2222-7333-8444-555555555555', hostId 'local'.
- It is a Codex conversation in the same app. The user now wants the main app window to show it.

**Answer:** `mcp__codex_app__navigate_to_codex_page`

Navigate to the known task, which is the explicit purpose of this real tool.

**Nearest alternatives:**

- `mcp__codex_app__read_thread`: Retrieving summaries would not switch the app to the requested conversation.
- `mcp__codex_app__open_in_codex`: That tool opens panels within a task and explicitly does not navigate the app to a conversation.
- `mcp__codex_app__list_threads`: The exact identity has already been resolved.

## CDX-04

**Family:** codex; **scenario group:** new-task-prerequisite

**Request:** Start a separate Codex task to add CSV export in the Ledger project.

**Context:**

- The current task belongs to a different repository.
- The user's saved project is called Ledger, but no available-project listing has been retrieved in this conversation. Its projectId, host, and Git-repository flag are unknown.
- The user explicitly wants a separate project task.

**Answer:** `mcp__codex_app__list_projects`

The real create_thread contract requires listing projects first, obtaining projectId and isGitRepository before creating a project task.

**Nearest alternatives:**

- `mcp__codex_app__create_thread`: Creating it now would require inventing the project ID and environment information.
- `mcp__codex_app__create_worktree`: It would isolate the current repository, which is a different project, in the current task.
- `mcp__codex_app__fork_thread`: Copying this task's history would not resolve or select the requested project.
- `exec_command`: A filesystem directory search does not supply the saved Codex project ID.

## CDX-05

**Family:** codex; **scenario group:** new-task-prerequisite

**Request:** Go ahead and start that CSV export task in Ledger.

**Context:**

- The user previously asked for a separate Codex task to add CSV export with a header row to Ledger's transaction table.
- The just-completed project listing returned {projectId:'ledger-local', name:'Ledger', isGitRepository:true}; the user confirmed this is the intended project.
- No task has been created yet. The user has not requested a particular starting branch, model, or use of the saved checkout directly.

**Answer:** `mcp__codex_app__create_thread`

Create the explicitly requested new project task now that the required project listing has supplied its ID and Git status.

**Nearest alternatives:**

- `mcp__codex_app__list_projects`: The required listing is already complete and the intended result confirmed.
- `mcp__codex_app__create_worktree`: It attaches an isolated checkout to the current task rather than creating the separate task requested.
- `mcp__codex_app__fork_thread`: The user asked for a new CSV task in the selected project, not a copy of this conversation.

## CDX-06

**Family:** codex; **scenario group:** new-task-versus-current-isolation

**Request:** Let's try the dependency upgrade in an isolated checkout attached to this same task.

**Context:**

- This task is already attached to /workspace/ledger, a Git repository. A completed status check showed a clean tree and valid HEAD.
- The user wants to keep the investigation in this conversation and leave the original checkout available for comparison.
- No managed worktree has yet been created for this task.

**Answer:** `mcp__codex_app__create_worktree`

Create and attach a managed Git worktree for the current task; this matches the real tool's scope exactly.

**Nearest alternatives:**

- `mcp__codex_app__create_thread`: The user asked to keep the work in this task rather than create another.
- `mcp__codex_app__fork_thread`: A fork creates a child task and copies conversation history.
- `exec_command`: A bare git worktree command would not perform the requested Codex managed attachment to this task.

## CDX-07

**Family:** codex; **scenario group:** new-task-versus-copy-history

**Request:** Make a separate copy of this Codex conversation, including what we've already worked out, so I can pursue the alternative there.

**Context:**

- The current task is idle; all turns and their responses are complete.
- The alternative should use the same working directory, and the user wants the completed conversation history carried over.
- The user will type the alternative's instructions in the new task, so no follow-up work needs to start there yet.

**Answer:** `mcp__codex_app__fork_thread`

Fork the existing conversation with its completed history and same directory.

**Nearest alternatives:**

- `mcp__codex_app__create_thread`: Starting a fresh task does not preserve the completed conversation history.
- `mcp__codex_app__create_worktree`: Creating a checkout does not create a copy of the conversation.
- `mcp__codex_app__read_thread`: Reading the history does not create the requested separate task.

## CDX-08

**Family:** codex; **scenario group:** pr-created-versus-detached

**Request:** The PR is created. Finish linking it to this Codex task so I can find it here later.

**Context:**

- The previous shell command successfully created the implementation PR and returned https://github.com/acme-fixtures/ledger/pull/418.
- The URL is known. This PR is the output of the current task, and no app attachment call has been made for it yet.

**Answer:** `mcp__codex_app__attach_artifact`

Attach the newly created PR to the task, as the real tool contract requires after PR creation.

**Nearest alternatives:**

- `mcp__codex_app__list_artifacts`: The context already establishes that the new PR has not been attached; a listing would not perform the requested attachment.
- `mcp__codex_app__open_in_codex`: Opening a PR page or review panel does not persist a task attachment.
- `exec_command`: The GitHub PR already exists; the remaining operation is Codex app attachment.

## CDX-09

**Family:** codex; **scenario group:** pr-created-versus-detached

**Request:** Unlink that old PR from this task; keep the PR itself open.

**Context:**

- The current task's attachment listing contains https://github.com/acme-fixtures/ledger/pull/392 and https://github.com/acme-fixtures/ledger/pull/418.
- The user explicitly identified pull/392 as the old PR to unlink. The new PR should stay attached.
- Both URLs and the selected attachment are already known.

**Answer:** `mcp__codex_app__remove_artifact`

Remove the specified PR attachment. The tool explicitly leaves the actual PR unchanged.

**Nearest alternatives:**

- `mcp__codex_app__list_artifacts`: The attachments and selected URL have already been retrieved.
- `mcp__codex_app__attach_artifact`: It adds an attachment rather than removing one.
- `exec_command`: Closing or editing the GitHub PR would not satisfy the requested app-only unlink.

## CDX-10

**Family:** codex; **scenario group:** wait-on-known-active-task

**Request:** Let me know when the CSV export task is finished or needs my attention.

**Context:**

- The separate Codex task is running with threadId '01b11111-2222-7333-8444-555555555555', hostId 'local'.
- The last wait response supplied afterCursor 'cursor-csv-7' and reported ongoing work.
- The user means waiting during this active session, not creating a recurring notification or later automation.

**Answer:** `mcp__codex_app__wait_threads`

Wait for a completion or attention event on the known active task using the saved cursor.

**Nearest alternatives:**

- `mcp__codex_app__read_thread`: Reading recent summaries does not subscribe to the completion/attention event and would invite repeated status polling.
- `mcp__codex_app__list_threads`: The task is already identified.
- `mcp__codex_app__get_handoff_status`: There is no handoff operation ID; this is task work, not a move between checkouts.

## LIN-01

**Family:** linear; **scenario group:** issue_detail_and_bulk_fields

**Request:** For API-184, show what is blocking it, any related or duplicate issues, and whether someone attached a reproduction.

**Context:**

- The saved Linear connection is reachable in this scenario. The previous issue-list result identified API-184 as 'Retry requests fail after token rotation'.
- That result contained the title, assignee, and status; attachments and issue relations have not been retrieved.

**Answer:** `mcp__linear__get_issue`

The issue is already identified, and the exact issue lookup provides attachments and can include blocking, related, and duplicate relations.

**Nearest alternatives:**

- `mcp__linear__list_issues`: It can return extensive issue fields, including descriptions and git branches, but its declared selectable fields do not include attachments or issue relations.
- `mcp__linear__list_comments`: Comments may discuss blockers or contain uploads, but they are not the issue's actual relation and attachment records.
- `exec_command`: The visible host policy prefers the existing Linear MCP connection for this service read.

## LIN-02

**Family:** linear; **scenario group:** issue_detail_and_bulk_fields

**Request:** Give me the titles and git branch names for my high-priority API issues that are In Progress and were updated on or after September 15.

**Context:**

- The date is September 18, 2026. The existing Linear connection has already resolved the team name to API.
- 'High' is priority 2, and 'In Progress' is an available status in this team. The requested issues have not yet been listed.
- The user wants a table covering all matching issues, not a particular known issue.

**Answer:** `mcp__linear__list_issues`

The issue listing supports assignee me, team, priority, state, updatedAt, and the title and gitBranchName result fields, so it can retrieve this filtered set directly.

**Nearest alternatives:**

- `mcp__linear__get_issue`: It also supplies a git branch name, but requires a known issue ID and does not discover the requested set.
- `mcp__linear__list_issue_statuses`: The status is already known; listing the team's status definitions would not retrieve matching issues.
- `exec_command`: The existing Linear MCP route is preferred by the host policy.

## LIN-03

**Family:** linear; **scenario group:** project_identity_and_discussion

**Request:** I'm preparing kickoff notes for P-API-12. Bring back its linked resources and the first page of customer needs attached directly to the project.

**Context:**

- The previous Linear search identified P-API-12 as the 'Resilient API' project.
- The search result showed its name and summary. Project resources and customer needs have not been fetched.
- The saved Linear connection is available for this read.

**Answer:** `mcp__linear__get_project`

P-prefixed identifiers identify projects. The project lookup explicitly supports including resources and a page of customer needs attached to that project.

**Nearest alternatives:**

- `mcp__linear__get_issue`: Its contract explicitly says that P-prefixed identifiers are projects, not issues.
- `mcp__linear__list_projects`: It supports many project fields, members, and milestones, but does not declare the requested resources or customer-needs inclusion controls.
- `mcp__linear__list_documents`: It can list project documents, but linked resources also include links and attachments, and it does not retrieve project customer needs.
- `exec_command`: The host policy prefers reusing the Linear MCP connection.

## LIN-04

**Family:** linear; **scenario group:** project_identity_and_discussion

**Request:** Who objected to the retention paragraph on P-API-12, and what did they say? Include the comments attached to the paragraph as well as the general project discussion.

**Context:**

- P-API-12 is the previously resolved 'Resilient API' Linear project.
- The project description has been read and contains the paragraph beginning 'Retain request traces for 30 days'. Its discussion has not been read.
- The user saw a comment marker beside that paragraph in Linear.

**Answer:** `mcp__linear__list_comments`

The comment listing accepts a project identifier and returns both top-level discussion and inline description comments, with quotedText identifying the anchored paragraph and author information.

**Nearest alternatives:**

- `mcp__linear__get_project`: It retrieves project details, but its declared inclusion options do not retrieve the project's discussion or anchored comments.
- `mcp__linear__get_diff_threads`: This reads review threads on a Linear diff; the known object is a project description.
- `mcp__linear__get_document`: The paragraph is part of the project description, not a separate identified document, and the request concerns its comments.
- `exec_command`: The existing Linear MCP route is preferred by the host policy.

## LIN-05

**Family:** linear; **scenario group:** document_discovery_and_exact_read

**Request:** Find the rollout documents in that Linear project that have been edited since September 14, and bring back their titles and content for me to compare.

**Context:**

- The date is September 18, 2026. 'That project' refers to the already resolved Linear project 'Resilient API', UUID 6d6a5c80-7f9b-4ed3-a3ca-1a8f08754e21.
- The user has not supplied document IDs or slugs. Earlier project notes suggest more than one document uses the term 'rollout'.
- The document search has not yet been run.

**Answer:** `mcp__linear__list_documents`

The document listing supports a search query, projectId, updatedAt, and explicit title/content fields, so it can discover the relevant documents and return their content together.

**Nearest alternatives:**

- `mcp__linear__get_document`: It is an exact lookup requiring a document ID or slug, neither of which is known.
- `mcp__linear__get_project`: It can include project resources, but does not offer the requested document search and updatedAt filtering with content fields.
- `mcp__linear__list_issues`: Its query searches issue titles or descriptions, not the workspace's document collection.
- `exec_command`: The existing Linear MCP connection is the host-preferred route.

## LIN-06

**Family:** linear; **scenario group:** document_discovery_and_exact_read

**Request:** Read the migration plan we found and summarize its rollback procedure.

**Context:**

- The preceding Linear document search returned the exact document titled 'Token migration plan', with slug token-migration-plan-7c81b4.
- Only its title, slug, and URL were included in the earlier result; its body is not in context.
- The user confirmed that this is the intended document.

**Answer:** `mcp__linear__get_document`

The target document is resolved to an exact slug, so the direct document lookup is the best next read of its body.

**Nearest alternatives:**

- `mcp__linear__list_documents`: It can include document content, but would repeat a discovery query; it has no exact document ID or slug filter.
- `mcp__linear__list_comments`: It can read a document's comments, but the requested rollback procedure is in the document body.
- `mcp__linear__get_project`: The project lookup can return linked resources, but the specific document has already been found and its body is needed.
- `exec_command`: The existing Linear MCP connection is preferred for this service read.

## LIN-07

**Family:** linear; **scenario group:** review_queue_exact_review_and_threads

**Request:** Which open reviews in fable/backend are still waiting for my review in Linear?

**Context:**

- The user is asking about their Linear review queue. Repository owner fable and repository name backend were established earlier in this task.
- The saved Linear connection is available, and no specific pull request or diff has been selected.

**Answer:** `mcp__linear__list_diffs`

The diff listing supports repository owner/name, status, reviewer me, and pending reviewer state, directly matching the queue request.

**Nearest alternatives:**

- `mcp__linear__get_diff`: An exact lookup requires a review URL, identifier, or slug; none is selected and the user requests a filtered queue.
- `mcp__linear__get_diff_threads`: It reads discussions for an already identified diff, not the user's review queue.
- `mcp__linear__list_issues`: Linear review assignments and reviewer state are diff filters, not issue assignee or state filters.
- `exec_command`: The user requested the Linear queue, and host policy prefers its existing MCP connection.

## LIN-08

**Family:** linear; **scenario group:** review_queue_exact_review_and_threads

**Request:** Bring back the details of the retry-backoff review from that list so I can inspect the review itself.

**Context:**

- The preceding Linear diff list identified one exact review titled 'Retry backoff for transient failures', with diff slug retry-backoff-9f22ab.
- The earlier result was a compact list entry. No exact review lookup or discussion lookup has been performed.
- The user has selected this review, not requested another search through the queue.

**Answer:** `mcp__linear__get_diff`

An exact diff slug is known, and the user asks to retrieve that review's details, which is the purpose of the exact diff lookup.

**Nearest alternatives:**

- `mcp__linear__list_diffs`: It can search by a bare slug, but the review is already selected; the exact lookup is the direct tool for its details.
- `mcp__linear__get_diff_threads`: It retrieves review discussions and the user's drafts; those are not what the user has requested at this step.
- `mcp__linear__get_issue`: A diff slug identifies a review, not a Linear issue.
- `exec_command`: The known object is in Linear and the host policy prefers the existing MCP route.

## LIN-09

**Family:** linear; **scenario group:** review_queue_exact_review_and_threads

**Request:** Now bring back the unresolved discussions on that review, including my drafts, so I can see what still needs an answer.

**Context:**

- The exact Linear review with slug retry-backoff-9f22ab has already been retrieved.
- Its details are available, but review threads and the authenticated user's draft comments have not yet been read.

**Answer:** `mcp__linear__get_diff_threads`

The diff-thread lookup supports filtering by resolved state and explicitly returns the authenticated user's drafts for an exact review identifier.

**Nearest alternatives:**

- `mcp__linear__get_diff`: The review details have already been retrieved; this tool's contract does not expose the resolved-thread filter or promise the user's drafts.
- `mcp__linear__list_comments`: Its supported parents are issues, projects, initiatives, documents, milestones, and status updates, not diffs.
- `mcp__linear__list_diffs`: It lists review objects and can filter reviewer state, but reviewer state is not unresolved discussion state.
- `exec_command`: The existing Linear MCP route is preferred by the host policy.

## LIN-10

**Family:** linear; **scenario group:** workflow_definition

**Request:** Before we map our importer states, show me every issue status currently configured for the API team, including statuses with no issues in them.

**Context:**

- The API team name was resolved in a prior successful Linear read.
- The user is inspecting the team's workflow configuration. No status mapping will be changed in this step.
- An earlier issue sample contained Todo and In Progress, but it did not enumerate the team's configured statuses.

**Answer:** `mcp__linear__list_issue_statuses`

The team status listing retrieves available issue statuses directly, including definitions that cannot be inferred from the currently populated issue set.

**Nearest alternatives:**

- `mcp__linear__list_issues`: It can return each issue's status, but listing issues cannot establish statuses that currently contain no issues.
- `mcp__linear__get_project`: Issue statuses are team workflow configuration, not project metadata.
- `mcp__linear__list_milestones`: Project milestones are distinct from team issue-status definitions.
- `exec_command`: The existing Linear MCP connection is preferred by the host policy.

## SLK-01

**Family:** slack; **scenario group:** channel_history_and_thread_replies

**Request:** Catch me up on the latest 15 messages posted to #release-room.

**Context:**

- The Slack channel has already been resolved to C0FABLEOPS1, a public channel.
- The saved Slack connection read this channel successfully earlier in the scenario, but the latest messages have not been fetched.
- The user is asking for the recent channel timeline; no individual discussion thread is selected.

**Answer:** `mcp__slack__slack_read_channel`

The channel is known and the request is for its recent history. The channel read returns messages newest first and supports a 15-message limit.

**Nearest alternatives:**

- `mcp__slack__slack_read_thread`: It requires a selected parent message and retrieves that thread's replies, not the channel timeline.
- `mcp__slack__slack_search_public`: It can search a known channel, but the user requests a bounded recent timeline with no content search to perform.
- `mcp__slack__slack_search_channels`: The channel identity is already resolved.
- `exec_command`: The host policy prefers the existing Slack MCP connection.

## SLK-02

**Family:** slack; **scenario group:** channel_history_and_thread_replies

**Request:** Read the discussion under the release-freeze announcement and tell me what the team decided.

**Context:**

- A prior channel-history result from C0FABLEOPS1 identified the release-freeze announcement with parent message timestamp 1789718400.000200.
- The announcement has six replies. The history result included the parent text and reply count, but not the replies.
- The user is referring to this exact announcement.

**Answer:** `mcp__slack__slack_read_thread`

The known parent channel and timestamp identify the discussion, and the thread read retrieves the parent plus its replies.

**Nearest alternatives:**

- `mcp__slack__slack_read_channel`: Its contract directs callers to the thread tool for replies; rereading channel history would not be the targeted discussion read.
- `mcp__slack__slack_search_public`: The thread is already located, and search results with surrounding context are not the direct retrieval of its full reply sequence.
- `mcp__slack__slack_get_reactions`: Reactions may signal sentiment, but they cannot reveal the decision expressed in the unread replies.
- `exec_command`: The existing Slack MCP route is preferred by the host policy.

## SLK-03

**Family:** slack; **scenario group:** channel_discovery_and_message_search

**Request:** Find the Slack channel where the data-platform team coordinates warehouse migrations, and give me its channel ID and purpose.

**Context:**

- The saved Slack connection is available. The user does not remember the channel name, and no candidate channel ID is known.
- The directory is expected to describe the channel's purpose using terms such as warehouse or migrations.
- The request concerns locating the channel itself, not finding a particular message.

**Answer:** `mcp__slack__slack_search_channels`

The channel directory search matches channel names and attributes and returns IDs, topics, purposes, and archive status.

**Nearest alternatives:**

- `mcp__slack__slack_search_public`: It searches message and file content; the user wants the channel directory record and its purpose.
- `mcp__slack__slack_read_channel`: It requires a known channel or user ID, and the channel has not been resolved.
- `mcp__slack__slack_search_users`: It searches people and their profile attributes, not channel records.
- `exec_command`: The existing Slack MCP connection is the host-preferred route.

## SLK-04

**Family:** slack; **scenario group:** channel_discovery_and_message_search

**Request:** Find the public Slack discussion where we agreed on the event-schema compatibility rules.

**Context:**

- The saved Slack connection is available, but no channel or parent message has been identified.
- The user remembers the topic, not the channel. No consent has been given to use the search that includes private channels and DMs.
- The relevant discussion is expected to be in a public channel.

**Answer:** `mcp__slack__slack_search_public`

A content search across public channels matches the scope and needs no additional consent under the real tool description.

**Nearest alternatives:**

- `mcp__slack__slack_search_public_and_private`: It can restrict channel types, but the tool metadata says to request and wait for consent before using this tool; that consent is absent.
- `mcp__slack__slack_search_channels`: It searches channel names and attributes, not the messages that record the compatibility decision.
- `mcp__slack__slack_read_thread`: The parent channel and timestamp needed to read a specific discussion are not yet known.
- `exec_command`: The visible host policy prefers the existing Slack MCP route.

## SLK-05

**Family:** slack; **scenario group:** public_and_authorized_private_search

**Request:** Yes, include my private channels and DMs. Find where Priya gave me the revised cutover date.

**Context:**

- The assistant previously asked whether the date search could include private channels and direct messages; the user's current reply explicitly grants that consent.
- Priya's Slack user ID is already known as U0FABLEPRY1. No matching message, channel, or parent timestamp has been found.
- The user remembers discussing the cutover sometime this month and is unsure whether it happened in a private project channel or a DM.
- The saved Slack connection is available.

**Answer:** `mcp__slack__slack_search_public_and_private`

The user has supplied the consent required by the tool metadata, and finding an unidentified message across private channels and DMs requires the broader search.

**Nearest alternatives:**

- `mcp__slack__slack_search_public`: It cannot search the private messages explicitly included in the request.
- `mcp__slack__slack_read_channel`: It can read Priya's DM history using a user ID, but the message may instead be in an unknown private project channel.
- `mcp__slack__slack_search_users`: Priya is already resolved; the missing object is a message about the cutover date.
- `exec_command`: The host policy prefers the existing Slack MCP connection.

## SLK-06

**Family:** slack; **scenario group:** file_body_and_canvas_structure

**Request:** Read the attached retry-debug.txt and summarize the errors it contains.

**Context:**

- A prior Slack thread read returned the file ID F0FABLEDBG1 for retry-debug.txt, with MIME type text/plain and size 64 KB.
- The thread text and file metadata are in context, but the attachment's content has not been retrieved.
- The saved Slack connection can access this file in the scenario.

**Answer:** `mcp__slack__slack_read_file`

The exact file ID is known, its size is below the declared limit, and the file read retrieves its text content.

**Nearest alternatives:**

- `mcp__slack__slack_read_thread`: The thread has already provided the file reference; retrieving the file's body is a separate supported read.
- `mcp__slack__slack_read_canvas`: The attachment is a plain text file, not a Slack Canvas.
- `mcp__slack__slack_search_public`: The attachment is already identified; a discovery search is unnecessary and does not replace the direct body read.
- `exec_command`: The existing Slack MCP route can read this file directly and is preferred by host policy.

## SLK-07

**Family:** slack; **scenario group:** file_body_and_canvas_structure

**Request:** Check the source canvas and show the Incident escalation section text with its Slack section ID so I can compare it with the import log.

**Context:**

- The user is debugging their canvas importer. Its log identifies sections by Slack section IDs and appears to have imported the Incident escalation section twice.
- A preceding Slack result identified the source Canvas as F0FABLECVS1. The canvas body and section mapping have not yet been read.
- The user only needs source information for this comparison; the import log is already visible in context.

**Answer:** `mcp__slack__slack_read_canvas`

The Canvas read explicitly returns markdown plus its section ID mapping, which is required to correlate the source section with the import log.

**Nearest alternatives:**

- `mcp__slack__slack_read_file`: It can read Canvas markdown for a summary, but the separate Canvas read explicitly returns the section ID mapping needed for this comparison.
- `mcp__slack__slack_search_public`: It can discover canvases by name or content, but this canvas is already identified and its section mapping is needed.
- `mcp__slack__slack_read_thread`: A thread read can supply file references and discussion, not the Canvas's section ID mapping.
- `exec_command`: The existing Slack MCP connection has the dedicated structural read and is preferred by host policy.

## SLK-08

**Family:** slack; **scenario group:** workspace_people_and_channel_membership

**Request:** Find the people in Slack whose profiles identify them as site reliability engineers, and give me their names and user IDs.

**Context:**

- The user is assembling a contact list across the workspace. No particular channel or individual has been selected.
- The saved Slack connection is available, and profile roles rather than message authorship are the source requested.

**Answer:** `mcp__slack__slack_search_users`

The user search supports profile attributes such as role, title, and department and can discover people across the workspace.

**Nearest alternatives:**

- `mcp__slack__slack_list_channel_members`: It enumerates a specified channel's members, but no channel is selected and membership would not define this workspace-wide role query.
- `mcp__slack__slack_read_user_profile`: It gives detailed information for a known user ID, not a discovery search for all people matching a role.
- `mcp__slack__slack_search_public`: It finds message and file content, which is different from searching profile role attributes.
- `exec_command`: The existing Slack MCP route is preferred by the host policy.

## SLK-09

**Family:** slack; **scenario group:** workspace_people_and_channel_membership

**Request:** For the Maya we just found, check her Slack timezone and current status before I choose a meeting time.

**Context:**

- The preceding user search resolved Maya Chen in infrastructure to Slack user ID U0FABLEMYA1, and the user confirmed the identity.
- That search used a concise result containing her name and user ID. Her timezone and current status have not been read.
- No meeting invitation or message is being sent.

**Answer:** `mcp__slack__slack_read_user_profile`

The user identity is resolved, and the exact profile read explicitly provides timezone and status.

**Nearest alternatives:**

- `mcp__slack__slack_search_users`: It can search profiles, but the person is already identified; its contract directs detailed lookup of a known user ID to the profile tool.
- `mcp__slack__slack_list_channel_members`: Detailed membership results can include profiles, but no membership question is asked and a channel read would be indirect.
- `mcp__slack__slack_read_channel`: Reading Maya's DM history would retrieve messages, not her current profile timezone and status.
- `exec_command`: The existing Slack MCP connection is preferred by host policy.

## SLK-10

**Family:** slack; **scenario group:** workspace_people_and_channel_membership

**Request:** Give me the current membership of #warehouse-migration, including bots, with names and user IDs.

**Context:**

- The channel has already been resolved to C0FABLEWHM1 and contains fewer than 30 members.
- The user is checking an onboarding roster. Message history from this channel is available, but its membership has not been listed.
- The saved Slack connection can read the channel in this scenario.

**Answer:** `mcp__slack__slack_list_channel_members`

The membership listing directly enumerates the known channel and supports including bots while returning profile details and user IDs.

**Nearest alternatives:**

- `mcp__slack__slack_search_users`: It discovers people by profile attributes, but does not declare a channel-membership filter.
- `mcp__slack__slack_read_channel`: Message authors are not a complete membership roster and omit members who have not posted.
- `mcp__slack__slack_search_channels`: It locates channel directory records; this channel is already known and its member list is needed.
- `exec_command`: The existing Slack MCP connection is the host-preferred route.

## NOT-01

**Family:** notion; **scenario group:** known_page_body

**Request:** Read the rollout note at https://www.notion.so/acme/Cache-rollout-3f8b0f404b69418595d34cdf6f9be427 and tell me the rollout stages and the exit condition for each.

**Context:**

- The earlier navigation result supplied the title Cache rollout and this exact page URL, but no page body. The requested stages have not been retrieved.
- The Notion connection is reachable in this scenario. Its enhanced Markdown specification has already been read in this session.

**Answer:** `mcp__notion__notion_fetch`

The page is already identified and the missing evidence is its body. Fetch retrieves a Notion page by URL; the host policy prefers the persisted Notion MCP route.

**Nearest alternatives:**

- `mcp__notion__notion_search`: Search would rediscover an already identified page and is not the direct retrieval of its full body.
- `mcp__notion__notion_get_comments`: The user asks for the stages documented in the page, rather than discussion content.
- `exec_command`: The host explicitly prefers the existing Notion MCP connection for Notion URLs.

## NOT-02

**Family:** notion; **scenario group:** content_search_access_contrast

**Request:** Find the Notion design note about quota rollover. I think those two words are in the title; I need the page link before our review.

**Context:**

- There is no page URL or ID in the conversation. The user has not visited or pinned this note and does not know its sidebar location.
- A completed access check for this connection reports that AI search is not available; ordinary search is available. Its restricted parameters include filters.title_only and sort values other than relevance. The access result is current.
- The user is identifying a document about quota behavior, not a Notion user account.

**Answer:** `mcp__notion__notion_search`

This is a keyword content search for an unidentified page. The required access check is already complete and explicitly makes ordinary search the prescribed content-search route; the supplied short keywords need no restricted filters.

**Nearest alternatives:**

- `mcp__notion__notion_fetch`: Fetch needs an entity URL or ID, which has not been discovered.
- `mcp__notion__notion_list_recent_pages`: Recent navigation does not identify a note the user has never visited.
- `mcp__notion__notion_list_favorite_pages`: The note is not known through a favorite or pinned item; the contract directs content searches to the available content-search tool.
- `exec_command`: The existing Notion MCP content-search route is preferred by the visible host policy.
- `mcp__notion__notion_ai_search`: Although this tool documents a keyword fallback, the current access result and both search contracts explicitly prescribe ordinary search when AI search is unavailable.
- `mcp__notion__notion_get_tool_access`: The required current access result is already in context and should be reused.

## NOT-03

**Family:** notion; **scenario group:** anchored_discussion_content

**Request:** What did Leah and Omar agree in the review thread attached to the retry-window paragraph? Include the replies that led to the decision.

**Context:**

- The page Retry policy, ID 428aa45d-70cb-46f4-9cda-68f23c347db8, has already been retrieved with discussion indicators. Its body is complete, with truncated=false and no unknown blocks.
- The retry-window paragraph has the discussion URL discussion://428aa45d-70cb-46f4-9cda-68f23c347db8/0bdf62b7-4f59-4cde-bd44-93154e671bb8/840d7d93-9331-4e51-8fa6-9f8e91d96cd6. The indicator contains a short preview and shows five comments, but the actual replies are not in context.
- The requested thread is an ordinary review discussion, not a suggested edit. The user wants its contents, without posting a reply.

**Answer:** `mcp__notion__notion_get_comments`

The page and anchored discussion are already identified. Get comments supplies full discussion threads, while page retrieval supplies only their indicators and previews.

**Nearest alternatives:**

- `mcp__notion__notion_fetch`: The page and anchor have already been retrieved; discussion indicators do not provide the missing full replies.
- `mcp__notion__notion_search`: The exact page and discussion are known, so content discovery is unnecessary.
- `exec_command`: The dedicated Notion discussion reader follows the persisted-connection policy.

## NOT-04

**Family:** notion; **scenario group:** workspace_roster_continuation

**Request:** Continue the Notion workspace roster. I need the remaining members and guests, with their account types, before I identify our service accounts.

**Context:**

- The first roster response returned 100 users with IDs, names, available emails, and person-or-bot types. It reported that more users remain and supplied next_cursor=user_roster_page_2_6d45.
- The roster is unfiltered; the user wants its continuation rather than a search for one named person. The first 100 records have already been retained.

**Answer:** `mcp__notion__notion_get_users`

Get users enumerates workspace members and guests with account types and accepts the cursor needed to continue this existing roster.

**Nearest alternatives:**

- `mcp__notion__notion_search`: It supports user searches, but its contract has no roster-continuation cursor and the user is not looking up a name or email.
- `mcp__notion__notion_fetch`: Its entity retrieval covers pages, databases, data sources, and views, rather than the workspace user roster.
- `exec_command`: The available Notion roster API is the preferred persisted connection.
- `mcp__notion__notion_ai_search`: Its user-search mode takes a name or email and has no workspace-roster pagination cursor; this is a continuation of an unfiltered roster.

## NOT-05

**Family:** notion; **scenario group:** navigation_recently_viewed

**Request:** Help me find the Notion page I kept opening this morning. Show the likely pages so I can recognize it; I can't remember any words from the title.

**Context:**

- The user clarified that they only read the page and did not edit it. They reopened it several times during their morning work.
- No page URL, ID, reliable keyword, or sidebar location is known. The account whose navigation history is needed is the current connected Notion user.

**Answer:** `mcp__notion__notion_list_recent_pages`

Recently viewed pages are ranked using recency and visit frequency, matching the user's navigation clue. Edit-time search would address a different event.

**Nearest alternatives:**

- `mcp__notion__notion_search`: There are no usable content clues; ordering by last edit would not recover the user's repeated reads.
- `mcp__notion__notion_list_favorite_pages`: Repeated visits do not establish that the page is a favorite.
- `mcp__notion__notion_fetch`: A particular page has not yet been identified.
- `exec_command`: The Notion navigation-context tool is available through the connection preferred by host policy.

## NOT-06

**Family:** notion; **scenario group:** navigation_pinned_order

**Request:** Give me the links to the Notion items I've starred, in the same order as my sidebar. I'll choose which ones belong in the onboarding reading list.

**Context:**

- The user means their own favorite pages and databases. They have not supplied individual titles or links, and some starred items have not been opened recently.
- The requested output is the current ordered collection of links, before any reading list is created or updated.

**Answer:** `mcp__notion__notion_list_favorite_pages`

The favorites listing returns the connected user's pages and databases in sidebar order, exactly the collection and ordering requested.

**Nearest alternatives:**

- `mcp__notion__notion_list_recent_pages`: It ranks visits by recency and frequency, which does not preserve the user's favorite collection or sidebar order.
- `mcp__notion__notion_search`: Content search is not the tool contract for the current user's ordered favorites.
- `mcp__notion__notion_list_private_pages`: Favorite items may come from private or shared locations; the Private section is a different collection.
- `exec_command`: The dedicated Notion favorites reader is preferred under the existing connection policy.

## NOT-07

**Family:** notion; **scenario group:** content_search_access_contrast

**Request:** Find the Notion design note about quota rollover. I think those two words are in the title; I need the page link before our review.

**Context:**

- There is no page URL or ID in the conversation. The user has not visited or pinned this note and does not know its sidebar location.
- A completed access check for this connection reports that AI search is available with no restricted parameters. The access result is current.
- The user is identifying a document about quota behavior, not a Notion user account.

**Answer:** `mcp__notion__notion_ai_search`

The connection reports AI search available. The actual tool contracts require it for every content search, including this short keyword or page-title request; wording does not determine which search tool to use.

**Nearest alternatives:**

- `mcp__notion__notion_search`: When current access reports AI search available, the search contracts explicitly direct content searches to AI search, including exact keywords and titles.
- `mcp__notion__notion_get_tool_access`: The required current access result is already present and should be reused.
- `mcp__notion__notion_fetch`: The page has not yet been identified by URL or ID.
- `mcp__notion__notion_list_private_pages`: This is a content search; the user has not identified a Private sidebar location to browse.
- `exec_command`: Host policy prefers the existing Notion MCP search connection.

## NOT-08

**Family:** notion; **scenario group:** content_search_access_contrast

**Request:** Find the Notion design note about quota rollover. I think those two words are in the title; I need the page link before our review.

**Context:**

- There is no page URL or ID in the conversation. The user has not visited or pinned this note and does not know its sidebar location.
- The Notion connection is reachable and its tool catalog is visible. No current access result has been obtained for this connection in this session; the conversation contains no information about AI-search availability or parameter restrictions.
- No content search has been attempted in this session. The user is identifying a document about quota behavior, not a Notion user account.

**Answer:** `mcp__notion__notion_get_tool_access`

Both content-search contracts require current access discovery before the first search when availability is unknown. Tool exposure or reachability does not decide whether AI or ordinary search is the prescribed route.

**Nearest alternatives:**

- `mcp__notion__notion_search`: Its contract requires the access check first and says missing access information is not a denial of AI access.
- `mcp__notion__notion_ai_search`: It also requires access discovery first when current availability is unknown.
- `mcp__notion__notion_fetch`: No target page URL or ID is known, and fetching an entity would not supply the current tool-access map.
- `mcp__notion__notion_list_shared_pages`: The user has a content query and no known Shared sidebar location; browsing that collection does not resolve the search prerequisite.
- `exec_command`: The existing MCP connection provides the required read-only access check and is preferred by host policy.

## NOT-09

**Family:** notion; **scenario group:** faithful_rich_text_rows

**Request:** Show me the Notes values for launch checks whose Status is In Progress. Keep the embedded person mentions and link destinations intact so I can compare them with our export.

**Context:**

- The Launch checks database has already been retrieved. Its data source is collection://6b09045d-73d4-4ad7-8b52-f597b8c522f1 and the fetched schema includes Name (title), Status (select with In Progress, Ready, and Done), and Notes (rich_text). No matching row page IDs are known yet.
- The current connection access result reports faithful structured row queries available with no restricted parameters. The schema retrieval and access check are complete.
- The earlier CSV export flattened Notes to plain text. The user is requesting a faithful read for comparison and has not asked to repair or rewrite anything. There are 18 launch checks in the source.

**Answer:** `mcp__notion__notion_query_data_sources`

Rows mode can filter this known single source and preserve rich-text mentions and link destinations. Its access and schema prerequisites are already satisfied.

**Nearest alternatives:**

- `mcp__notion__notion_query_multiple_data_sources`: This tool is SQL-only, and its own contract warns that SQL text may omit mentions, formatting, and link destinations. It also directs single-source work to query_data_sources.
- `mcp__notion__notion_fetch`: It can read an identified page faithfully, but the matching row IDs are not yet known. Fetching the data-source schema again would not perform the requested filtered row retrieval.
- `mcp__notion__notion_search`: Content search is not a faithful filtered rich-text property read from the known source.
- `exec_command`: The connection already provides the required faithful row retrieval and is the host's preferred route for Notion content.
- `mcp__notion__notion_get_tool_access`: The current access result is already known and should be reused; the database schema prerequisite is also satisfied.

## NOT-10

**Family:** notion; **scenario group:** async_operation_followup

**Request:** Did the onboarding draft import finish? Tell me whether it succeeded and, if so, which pages it created.

**Context:**

- The user previously authorized creating the drafts. That request returned an async_task handle with task_id=task_onboarding_7d28c4, status=running, and a suggested polling backoff of five seconds.
- Thirty seconds have elapsed since that response. No completion result or new page IDs have been received, and no status poll has yet been made.
- The immediate request is only to read the status and operation result of that existing task.

**Answer:** `mcp__notion__notion_get_async_task`

The original operation returned the exact task handle required by the asynchronous status tool, and the suggested backoff has elapsed. A successful status result includes the operation's result.

**Nearest alternatives:**

- `mcp__notion__notion_search`: Discovering similarly named pages cannot establish whether this particular import task succeeded or failed.
- `mcp__notion__notion_fetch`: The new page IDs are not known, and entity retrieval would not report the status of this async task.
- `mcp__notion__notion_list_recent_pages`: Recently viewed pages are navigation history, not the result of the pending import.
- `exec_command`: The connection exposes a direct read-only status operation for the supplied task handle.
