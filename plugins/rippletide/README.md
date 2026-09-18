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

The MCP server exposes `route`, `status`, and `report`. Model scores are diagnostic, and execution is unknown until supported by evidence. This is an explicit routing handoff, not an interception of Codex's internal model decisions.
