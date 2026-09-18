# Rippletide plugin

Local routing for registered repository-search tools, connected MCP tools, and named Codex specialists. Codex prepares arguments and executes the recommendation. A fallback leaves the decision with Codex.

Requires Apple Silicon macOS, `uv`, Python 3.12 (managed by uv), and Codex. Use the repository's user-test kit to create a configured example project.

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

The alternatives are native MLX builds of the model families listed by OpenJev,
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
