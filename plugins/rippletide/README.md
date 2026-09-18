# Rippletide plugin

Local routing for registered repository-search tools, connected MCP tools, and named Codex specialists. Codex prepares arguments and executes the recommendation. A fallback leaves the decision with Codex.

The default backend requires Apple Silicon macOS, `uv`, Python 3.12 (managed by uv), and Codex. Use the repository's user-test kit to create a configured example project. A separate experimental CPU backend is described below.

```sh
uv sync --frozen --python 3.12
uv run rippletide setup
uv run rippletide status --project-root /absolute/project
uv run rippletide serve
```

Setup downloads the pinned `harshatheg/Qwen-2.5-1B-RLCD` source and its documented `mlx-community/Qwen2.5-1.5B-Instruct-4bit` weights dependency. The weights are approximately 869 MB. Model data is stored outside this package and Git. The runtime uses MLX explicitly and does not substitute a different backend when unavailable.

Project configuration is `.rippletide/config.json`. The registry defines allowed capabilities and invocation schemas; project preferences can override general preferences. Use `rippletide preferences` only for an explicitly requested saved preference. Inspect the CLI's `--help` for arguments.

The MCP server exposes `route`, `status`, and `report`. Model scores are diagnostic, not calibrated confidence. Execution is unknown until supported by evidence.

## Model options

| Alias | Backend / pinned artifacts | Default |
| --- | --- | --- |
| `qwen25-rlcd` | `harshatheg/Qwen-2.5-1B-RLCD@2af86848be75847ccb3553b0941cc51d6ef7e4e9` engine; `mlx-community/Qwen2.5-1.5B-Instruct-4bit@8b403126fc14f14cfc99bb4cfa72ecbc129ea677` weights | Yes |
| `qwen3-0.6b` | `mlx-community/Qwen3-0.6B-4bit@73e3e38d981303bc594367cd910ea6eb48349da8` | No |
| `minicpm5-2b` | `openbmb/MiniCPM5-2B-MLX@8a9ad7539ac86281d0ac2b017ba04a5de53fe9a3` | No |
| `qwen3.5-4b` | `mlx-community/Qwen3.5-4B-4bit@0e7ffd5c629ef7719d4cbc04069232580bfa9d9c` | No |
| `qwen3-0.6b-torch` | Experimental float16 CPU backend; `Qwen/Qwen3-0.6B@c1899de289a04d12100db370d81485cdf75e47ca` | No |

The three MLX alternatives are native MLX builds of the model families listed by OpenJev,
not its exact GGUF artifacts. Setup verifies immutable source/config/tokenizer
metadata and weight checksums. Downloads and provenance stay outside Git.

```sh
uv run rippletide models
uv run rippletide setup --model qwen3-0.6b
RIPPLETIDE_MODEL=qwen3-0.6b uv run rippletide serve
```

`serve --model ALIAS` is equivalent. Model selection happens at server startup,
never through a model-generated routing argument. Omit it to retain `qwen25-rlcd`.
Each server keeps one warm worker. Alternatives use their native chat templates,
disabled thinking and validated single-token labels with an explicit defer option.
Cold startup and warm routing are reported separately.

The CPU alias requires the `cpu-lab` dependency extra and is for Windows/Linux
experiments. It does not use the AMD Vega GPU. The [lab instructions](../../experiments/README.md)
provide the tested installation path. Default routing still has a two-second
deadline; the CPU experiment's longer deadline is explicit and requires a run
directory. Successful offline inference is not proof of interactive readiness.

## Optional personalization

`rippletide learning status` reports whether a user profile exists. During
requested first-use setup, the skill can guide the user through optional
preferences and a choice to learn explicit corrections. There is no automatic
training merely because the plugin was downloaded.

```sh
# Use explicit preferences as context; no correction collection or training.
uv run rippletide learning init --user-id local-user --mode memory \
  --preference 'When either source is suitable, consult product documentation first.'
uv run rippletide learning status
```

Learning requires a compatible, explicitly selected direct-logit backend. The
default `qwen25-rlcd` engine is not supported by the new trainer. For a user who
has opted in, initialize with `--enable-learning --auto-train --mode lora`, or
update an existing profile through `learning configure --set JSON`. The CLI
also supports `feedback`, `train` and `rollback`; see `learning --help` and the
[guided setup reference](skills/route-capabilities/references/personalization.md).

The modes are `off`, `memory`, `residual` and `lora`. Memory changes the prompt.
Residual learning changes scores outside Qwen; LoRA changes trainable attention
adapters inside Qwen while preserving its base weights. Explicit rules retain
priority. Background training runs only while the MCP service is active and
after enough opted-in corrections. It suspends that worker, validates a candidate
before activation, and retains the previous version for rollback. A profile
change reloads the worker and can cause a temporary defer.

The profile is local process configuration through `RIPPLETIDE_PROFILE`, not a
routing-tool argument. By default it lives under `RIPPLETIDE_DATA_DIR/profile`.
Corrections can contain task text; they are not uploaded by the trainer. See the
[lab report](../../docs/PERSONALIZATION_LAB_REPORT.md) for exact methodology,
observed results and unsupported claims.

## Routing checks and evidence

The routing skill calls the MCP router before supported decisions. Pre/PostToolUse
hooks associate its response with a one-use receipt scoped to the actual session,
transcript, turn and operation. A registered call must match the selected route;
a defer allows one same-family fallback. Missing/mismatched receipts are blocked
with at most two corrective opportunities in the paired runner.

Coverage is explicit: recognizable native searches, registered information MCP
tools and configured named specialists. File edits, tests, direct reads and
unregistered tools are observed, not routed. Shell programs can hide other actions;
unparseable wrappers (for example a here-document containing prose quotes) are
recorded as `UNSUPPORTED_SHELL_SYNTAX`, not falsely authorized or blocked as edits.
These hooks are evidence/control aids, not a security boundary or universal
interception of Codex's internal decisions.

`RIPPLETIDE_RUN_DIR` separates private router/hook logs for each test arm. Outside
paired tests, only projects with `.rippletide/config.json` are collected. No
preferences are learned or changed without an explicit request. A fresh session
is required after installing/updating the plugin.
