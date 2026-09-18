# Session tool selection

The local scorer ("Jev") chooses the tool. Codex generates its arguments and
executes it afterward. The input is:

```json
{
  "context": "Current task context and observations",
  "question": "Which tool should run next to satisfy the user's request?",
  "tools": [
    {"name": "exec_command", "description": "Run a shell command."},
    {"name": "apply_patch", "description": "Edit files using a patch."}
  ]
}
```

The host supplies every currently callable tool with its exact identity and
description. It retains the schemas for subsequent argument generation. A tool
is one callable function, not a shell command strategy or a named agent role.
The selector itself is excluded to avoid recursion. Context and question are
data; neither can alter the supplied catalog.

`selection.select_tool` always calls the configured local model, even for one
candidate. There are no operation categories, preferences, heuristic choices,
shortlists, or LLM fallbacks. The result is:

```json
{"status": "selected", "tool": "exec_command", "score": 0.8}
```

The score is the existing uncalibrated candidate softmax, and selection is argmax
over the complete supplied catalog. Larger catalogs use distinct, validated
single-token labels in the same readout; they are not split into independently
normalized batches. Context is preserved up to the pinned model's declared
capacity. Oversized inputs, invalid catalogs, unavailable models, and timeouts
return `status: "error"` without a selected tool or fallback authorization.

This contract is separate from the historical `Router.route` experiment API.
The host integration and public MCP handoff migrate to this contract in the
dependent PRs. The historical A–D harness is not evidence of this new flow.
