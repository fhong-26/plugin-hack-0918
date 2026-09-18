# Rippletide / local Jev

A Codex plugin that selects the next tool using the repository's local model.
The patched Codex host sends the current context, question, and all callable
session tools to Jev. Jev chooses the candidate with the highest model score.
Codex then generates that tool's parameters and executes it.

The active path has no project registry, preferences, rule-based selection,
shortlist chosen by Codex, or fallback to Codex choosing another tool. A failed
selection stops the turn. Scores are candidate-relative, uncalibrated values;
this architecture does not establish better selection accuracy.

## Setup

Requires Apple Silicon macOS, `uv`, Python 3.12, Git, the Rust toolchain requested
by the pinned Codex source, and existing Codex authentication.

```sh
uv sync --locked --project plugins/rippletide
uv run --locked --project plugins/rippletide rippletide setup
python3 tools/codex/build.py
python3 scripts/install_plugin.py
build/codex-host/codex-rs/target/release/codex
```

The installer uses the locally built host, stages the plugin in the personal
marketplace, and preserves previous owned copies. It does not replace global
Codex. Start a fresh session after installation. The installer uses the existing
Codex `plugin-creator` helpers under `~/.codex/skills/.system/plugin-creator`.
If those helpers are unavailable, install this plugin with your host's plugin
management workflow instead.

**The patched CLI is required.** Installing the plugin in stock Codex Desktop or
the npm CLI cannot replace Codex's internal tool selection. All integration source
is in this repository as a small [pinned host patch](tools/codex/README.md).

## Runtime contract

The plugin exposes one MCP operation:

```json
{
  "context": "Current host instructions and conversation",
  "question": "Which tool should run next for the user's request?",
  "tools": [
    {"name": "exec_command", "description": "Execute a shell command"},
    {"name": "apply_patch", "description": "Edit files with a patch"}
  ]
}
```

The host supplies the complete catalog, including deferred MCP tools and hosted
web search. Disabled/hidden tools and the selector itself are excluded. The model
returns `{"status":"selected","tool":"exec_command","score":0.7}` or an explicit
error. Only the selected tool schema goes to Codex; the host checks its execution.
Codex can still answer in text when the task needs no further tool call.

There is one selection before each sampling request, including after tool results.
Full context is preserved up to the selected local model's context capacity.
Oversized requests fail explicitly. Cold model loading has a separate deadline;
full-context inference has a 60-second deadline.

See the [selection contract](docs/SELECTION_CONTRACT.md) and
[plugin/backend details](plugins/rippletide/README.md).

## Verification

```sh
uv run --locked --project plugins/rippletide pytest plugins/rippletide/tests
uv run --locked --project plugins/rippletide pytest --run-model \
  plugins/rippletide/tests/test_selection.py plugins/rippletide/tests/test_model_execution.py
```

The [host tests](tools/codex/README.md#verify-the-patch) verify native/MCP execution,
hosted tools, schema restriction, and rejection of invalid selections. Model tests
verify the actual local scorer and MCP transport; they do not establish quality
across arbitrary tasks.

## Historical experiments

The older registry/preference router, hook script, paired runner and reports remain
for historical experiments. They use the previous contract and are **not the active
plugin or an acceptance harness for this architecture**. The public MCP API now
accepts only the host selection contract above. Reproducing those experiments
requires the pre-change revision.

- [Original pilot](docs/PILOT_RESULTS.md)
- [Paired results](docs/PAIRED_RESULTS.md)
- [Historical test kit](user_tests/README.md)
- [Benchmark scenarios and provenance](docs/BENCHMARK_USER_SCENARIOS.md)
- [Benchmark experiment report](docs/BENCHMARK_EXPERIMENT_REPORT.md)

Remove the installed plugin with `codex plugin remove rippletide@personal` and
start a fresh session to disable routing. Model artifacts and retained test data
are not deleted.
