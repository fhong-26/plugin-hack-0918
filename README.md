# Rippletide

Rippletide is a local Codex plugin that recommends a registered tool or specialist using explicit preferences first, then a small Qwen model. Codex supplies arguments, executes the choice, and interprets the result.

**Status:** Working-pilot implementation. The runtime, real test services, and independent acceptance kit are here; see [pilot evidence](docs/PILOT_RESULTS.md) for what has actually passed and what remains unverified. This is not full benchmark validation.

## Start here

- [Product requirements](PRD.md): scope, user flow, routing behavior, test cases, definition of done, and proposed success criteria.
- [Plugin setup](plugins/rippletide/README.md): local engine, MCP operations, preferences.
- [User-test kit](user_tests/README.md): fresh projects, real MCPs, specialist agents, U01–U09.
- [Shared contract](docs/CONTRACT.md): registry, routing API, event formats.
- [Original ChatGPT response](chatgpt-response-prd-source.md): preserved source material.

## First version

The pilot routes repository searches, documentation/issue lookups, and bounded specialist assignments. Only explicitly registered and available capabilities are eligible. Preferences change only when the user asks.

The proposed flow is:

1. Codex sends an immediate goal and up to two relevant observations to Rippletide.
2. Rippletide checks tool availability and applies explicit preferences.
3. If rules do not settle the choice, the small model selects an allowed route or defers.
4. Codex receives the recommendation, supplies the tool arguments, and continues the task.

The router defers to Codex on uncertainty, an unavailable dependency, excessive context, or its two-second deadline. It is an explicit skill-driven handoff, not an interception of Codex's internal tool-selection loop. Recommendations alone are never counted as executed actions.

## Small model and integration

The required backend is [harshatheg/Qwen-2.5-1B-RLCD](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD), pinned to `2af86848be75847ccb3553b0941cc51d6ef7e4e9`. This repository supplies inference code, not weights. Its declared `mlx-community/Qwen2.5-1.5B-Instruct-4bit` dependency is pinned to `8b403126fc14f14cfc99bb4cfa72ecbc129ea677`. Both are downloaded explicitly; provenance and model files stay outside Git.

Requirements: Apple Silicon macOS, Python 3.12, `uv`, and an authenticated Codex CLI. Package environments and lockfiles are separate; the official Chroma MCP's older SDK is isolated from the SDK v2 router and fixture servers.

```sh
uv sync --locked --project plugins/rippletide
uv run --locked --project plugins/rippletide rippletide setup
uv sync --locked --project user_tests
python3 scripts/install_plugin.py
```

Installation stages an owned copy under `~/plugins/rippletide`, updates the personal marketplace through the plugin-creator scaffold, and installs through the Codex CLI. Previous owned copies are preserved on reinstall. Start a new session after installation. The fixture kit explicitly isolates A/B baselines from the installed plugin.

```sh
uv run --locked --project user_tests rippletide-uat prepare --scenario U02 --variant D
```

Use the returned workspace and prompt. `prepare`, `serve`, `check`, and `report` do not require importing the router. Generated databases, projects, logs, and acceptance results live under ignored `.uat-runs/`; model artifacts live under `~/.local/share/rippletide` by default.

To automate a genuine fresh Codex attempt and preserve its evidence:

```sh
python3 scripts/run_pilot.py --scenario U02 --variant D
python3 scripts/run_pilot.py --scenario U05 --variant D --semantic
python3 scripts/run_pilot.py --scenario U07 --variant D --failure tracker
python3 scripts/run_pilot.py --scenario U09 --variant A --comparison-scenario U05
python3 scripts/run_pilot.py --scenario U02 --variant D --installed-plugin
python3 scripts/summarize_pilot.py
```

The normal runner uses the development package and public skill copy, isolated from personal tools. `--installed-plugin` separately installs and verifies the package in a private temporary Codex home, using only the fixture services and default model settings. It archives the development skill/config outside the workspace and stops before the task if plugin discovery fails. Temporary authentication references are removed after the run; raw evidence is retained. See the [pilot report](docs/PILOT_RESULTS.md). The runner never converts a successful CLI exit into task success; review and finalize scenario assertions using the test kit.

## Verification

```sh
uv run --directory plugins/rippletide --locked pytest --run-model
uv run --directory user_tests --locked pytest
RIPPLETIDE_SEMANTIC_INTEGRATION=1 uv run --directory integrations/chroma --locked pytest
python3 -m unittest discover -s tests
```

Real-model and semantic-network checks are separately marked; their exact commands and observed results are recorded in the pilot report. Run tests from each package directory to avoid collecting deliberately buggy fixture projects.

## Disable and data retention

To stop loading the installed plugin, remove its local installation and start a
fresh Codex session:

```sh
codex plugin remove rippletide@personal
```

This removes the installed config/cache entry, not this source checkout, the
staged `~/plugins/rippletide` source, model artifacts, project preferences, or
retained test evidence. Reinstall with `python3 scripts/install_plugin.py`.
The independently configured development test servers are separate from the
personal installation; use variant A for a disabled comparison. No cleanup
command in this project recursively deletes model data or prior test attempts.

## Development milestones

1. Local pilot: genuine Qwen decisions followed by native-tool, MCP-tool, and specialist execution.
2. Small A–D smoke comparison: Codex alone, fixed guidance, rules, and rules plus Qwen.
3. Dedicated Linear/Notion acceptance once disposable project/page IDs and connectivity are supplied.
4. Full 40-task benchmark, followed by any fine-tuning or RL work.

Faster execution, lower token usage, and more consistent choices are goals to measure. The [PRD](PRD.md) defines proposed targets and distinguishes a completed implementation from a validated product. Fine-tuning and RL are later work.
