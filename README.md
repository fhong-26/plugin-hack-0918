# Rippletide

Rippletide is a local Codex plugin that chooses registered tools and specialists using explicit preferences first, then a small model. Codex supplies arguments, executes the choice, and interprets the result. Hooks check that supported calls follow a fresh routing decision.

**Status:** Experimental pilot with a paired test runner, routing checks, and four local model options. The first fixture pair was slower with Rippletide; the Linear/AGE-1349 enabled attempt stopped after incorrect tool selections. [Paired evaluation evidence](docs/PAIRED_RESULTS.md) records these results and limitations. Faster/cheaper/better is not established. [Original pilot evidence](docs/PILOT_RESULTS.md) is historical.

## Start a user test

After [one-time setup](#setup), run from this repository:

```sh
# Once per project: approve tools and the commands that check a correct result.
uv run --locked --project user_tests rippletide-uat configure --repo ~/projects/my-project \
  --check-argv '["uv","run","pytest"]'

# Each test: same task, same main commit, two NEW branches/worktrees in parallel.
uv run --locked --project user_tests rippletide-uat run --repo ~/projects/my-project \
  --task 'Fix the bug described in ...' --base main
```

The returned run directory contains `report.html`, `report.md`, and `report.json`:
time, parent/child token usage, interventions, tool-choice correctness, task checks,
and routing compliance. Private traces show Codex's requests, Rippletide's choices,
and actual calls; presentation reports omit sensitive text. A separate automated
judge supplies **provisional**, auditable correctness grades; its usage is separate.
Project tests alone are not independent proof of correctness.

Default tools are native search and two real specialists. Linear/other MCPs need a
one-time explicit read-only tool profile; they are not inherited from your personal
configuration. See [project onboarding and Linear](user_tests/README.md#test-an-existing-project).
No push, PR, ticket update, or modification of your original checkout is performed.
Use `--mode sequential --repeat 3` for repeated comparisons without simultaneous
resource contention. One pair cannot establish speed, cost, or determinism.

### Five ground-truth scenarios

After [setup](#setup) with **this branch's plugin**:

```sh
uv run --locked --project user_tests rippletide-uat benchmark run --cases B01 B02 B03 B04 B05
```

This creates fresh paired worktrees and synthetic tools, then checks calls/state
against local contracts derived from pinned BFCL/ToolSandbox entries. No Linear,
shopping or SMS account is used. See [benchmark setup and grading limits](user_tests/BENCHMARKS.md).
These are adapted user tests, **not official benchmark scores**. The latest five
default-model pairs, after the main-branch no-defer change, took 2.43× the summed
task time and 2.39× the Codex tokens with Rippletide. Trace-accounting gaps leave
automatic acceptance unknown; wrong selections and Codex preference overrides
were observed. See the [current report and prior comparison](docs/BENCHMARK_EXPERIMENT_REPORT.md).

## Tool-choice benchmark

Generate correctness, price and speed plots from the recorded 50-case comparison:

```sh
uv run benchmark/bench.py
```

[Benchmark instructions](benchmark/README.md) include a fresh Rippletide-versus-Codex run. The saved example measures the earlier Decision router, not this repository’s Rippletide plugin.

## Start here

- [Product requirements](PRD.md): scope, user flow, routing behavior, test cases, definition of done, and proposed success criteria.
- [Plugin setup](plugins/rippletide/README.md): local engine, MCP operations, preferences.
- [User-test kit](user_tests/README.md): fresh projects, real MCPs, specialist agents, U01–U09.
- [Five benchmark-derived user scenarios](docs/BENCHMARK_USER_SCENARIOS.md): source cases, ground truth, implemented local adapters and remaining official-scorer work.
- [Experiment report](docs/BENCHMARK_EXPERIMENT_REPORT.md): scenarios, expected and observed behavior, default-model measurements, trace limitations and per-case reports.
- [Shared contract](docs/CONTRACT.md): registry, routing API, event formats.
- [Original ChatGPT response](chatgpt-response-prd-source.md): preserved source material.

## First version

The pilot routes repository searches, documentation/issue lookups, and bounded specialist assignments. Only explicitly registered and available capabilities are eligible. Preferences change only when the user asks.

The flow is:

1. Codex sends an immediate goal and up to two relevant observations to Rippletide.
2. Rippletide checks tool availability and applies explicit preferences.
3. If rules do not settle the choice, the small model selects the best allowed route.
4. Codex supplies arguments. A hook checks the next registered call against that decision, then Codex executes it.

The model must choose when inference succeeds and eligible routes remain. The router still defers to Codex for operational failures such as an unavailable dependency, excessive context, or its two-second deadline. Defer permits one fallback in the same operation family. Receipts are session/turn-scoped and single-use; missing or mismatched decisions trigger bounded corrections. This is a skill-driven handoff checked at supported tool boundaries, not universal interception of Codex's internal reasoning or arbitrary shell programs. Unregistered calls remain visible but are not claimed as routed. Recommendations alone never count as executed actions.

## Models

The required backend is [harshatheg/Qwen-2.5-1B-RLCD](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD), pinned to `2af86848be75847ccb3553b0941cc51d6ef7e4e9`. This repository supplies inference code, not weights. Its declared `mlx-community/Qwen2.5-1.5B-Instruct-4bit` dependency is pinned to `8b403126fc14f14cfc99bb4cfa72ecbc129ea677`. Both are downloaded explicitly; provenance and model files stay outside Git.

The default remains the original RLCD engine. Optional aliases are `qwen3-0.6b`,
`minicpm5-2b`, and `qwen3.5-4b`, using pinned native MLX artifacts—not the exact GGUF
builds distributed by OpenJev. Install once, then select for a run:

```sh
uv run --locked --project plugins/rippletide rippletide setup --model qwen3-0.6b
uv run --locked --project user_tests rippletide-uat run --repo ~/projects/my-project \
  --task 'Fix ...' --router-model qwen3-0.6b
```

See [model provenance and configuration](plugins/rippletide/README.md#model-options).

## Setup

Requirements: Apple Silicon macOS, Python 3.12, `uv`, Node/npm, and authenticated Codex. The paired runner uses repository-local Codex **0.155.0**, pinned for verified hook support. It does not replace your global CLI. Package environments and lockfiles are separate; the Chroma MCP's older SDK is isolated from the SDK v2 router and fixture servers.
Other CLI/desktop host versions are not automatically certified; the runner checks
actual hook delivery and execution before starting a measured task.

```sh
uv sync --locked --project plugins/rippletide
uv run --locked --project plugins/rippletide rippletide setup
uv sync --locked --project user_tests
npm ci --prefix tools/codex --ignore-scripts --no-audit --no-fund
python3 scripts/install_plugin.py
```

Installation stages an owned copy under `~/plugins/rippletide`, updates the personal marketplace through the plugin-creator scaffold, and installs through the Codex CLI. Previous owned copies are preserved on reinstall. Start a new session after installation. The fixture kit explicitly isolates A/B baselines from the installed plugin.

## Seeded scenario tests

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
RIPPLETIDE_HOST_INTEGRATION=1 python3 -m unittest discover -s tests -p test_host_hooks.py
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
