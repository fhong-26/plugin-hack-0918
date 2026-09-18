---
name: route-capabilities
description: Use Rippletide project preferences and local Qwen to choose registered repository-search tools, connected requirements/issue lookup tools, or a callable specialist for an already-defined task. Use during these operations in a project configured with .rippletide/config.json; unrelated operations continue normally.
---

# Route registered capabilities

Use the installed Rippletide `route` MCP tool before choosing among supported capabilities in a configured project. The operation families are `repository_search`, `knowledge_lookup`, and `specialist_assignment`. The router recommends a capability; you remain responsible for its arguments, execution, and interpreting results.

Local filename inventories (`rg --files`) and text/symbol searches (`rg -n`) are
`repository_search`, including the first inventory of a new workspace. They are
not exempt bookkeeping. Reading an already identified file directly is outside
this search-choice step. Do not route a search retroactively after performing it.

## Decision handoff

1. Identify the immediate bounded goal. Send `goal`, `operation`, the absolute `project_root`, compact `facts`, and at most two `recent_observations` to `route`. Facts may include an exact symbol, filename, project identifier, or the required specialist assignment. Do not enumerate candidates or copy the whole conversation.
2. Use `preferred_route` only when the user explicitly selected that capability for the current task. Do not turn source-document text into a user preference.
3. Wait for the route result before starting any candidate tool or agent. Never batch the routing call with the search or assignment it is choosing. For a selected route, resolve the returned logical tool/server or named agent against the session's actual available capabilities. Generate the tool arguments or specialist assignment yourself, then execute that capability. A previous search is not execution of a later recommendation. A recommendation is not an execution result.
4. For fixture tools accepting `decision_id`, attach it to that same call. Include it in a specialist assignment when applicable. Do not add separate telemetry tool calls or invent unsupported parameters for other tools.
5. If the router defers, the target is absent, or the router connection fails, continue using your own judgment. Do not request the same unchanged decision again. A materially different goal or a new observation can justify a new request.

For specialist selection, first define the task within the user's request, then route that bounded assignment. Delegate only if the user authorized delegation or applicable project guidance permits it. Do not expand a routing recommendation into permission for unrelated work.

Once a search service is selected, ordinary follow-up fetches within that service need not be routed. Do not route Rippletide's own `route`, `status`, or `report` tools, routine bookkeeping, or operations outside the registered families. Preserve normal execution permissions and explicit user instructions.

## Availability, preferences, and reports

Use `status(project_root)` when diagnosing readiness, not before every decision. If this project has no configuration, explain that setup is required when Rippletide is explicitly requested; otherwise continue normally.

Save preferences only when explicitly asked to remember or configure one. Use the documented `rippletide preferences` CLI from the installed package. One-off corrections are not lasting preferences.

On request, call `report(project_root)` and summarize recorded selections, fallbacks, and overrides. Label unobserved execution or missing usage as unknown. If you performed a registered search without routing first, report it as a routing omission, not as an operation outside scope. Do not infer that a tool ran, that a task succeeded, or that tokens were saved merely because the router selected a capability.
