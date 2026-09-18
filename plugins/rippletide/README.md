# Rippletide plugin

The local model (called Jev here) selects a tool from the current Codex session's
complete callable catalog. The patched host sends context, question, and tool
names/descriptions; Codex fills parameters and executes the selected tool.

Requires Apple Silicon macOS, `uv`, Python 3.12, and the
[patched Codex host](../../tools/codex/README.md). From this directory:

```sh
uv sync --locked --python 3.12
uv run rippletide setup
uv run rippletide serve
```

The only public MCP operation is `route(context, question, tools)`; see the
[contract](../../docs/SELECTION_CONTRACT.md). No project registry or preferences
participate. A successful response contains only status, tool name and score.
Failure is an error with no alternative tool or fallback. The host handles
argument generation, approvals and execution; the skill explains that handoff.
No receipt hooks run in this workflow.

Setup explicitly downloads pinned engine code and weights, outside this package
and Git. The default uses the existing RLCD engine with MLX and approximately
869 MB of weights. Model scores are uncalibrated candidate-relative softmax
values. Inference selects the argmax without autoregressive answer generation.

## Existing model options

| Alias | Pinned artifacts | Default |
| --- | --- | --- |
| `qwen25-rlcd` | `harshatheg/Qwen-2.5-1B-RLCD@2af86848be75847ccb3553b0941cc51d6ef7e4e9`; weights `mlx-community/Qwen2.5-1.5B-Instruct-4bit@8b403126fc14f14cfc99bb4cfa72ecbc129ea677` | Yes |
| `qwen3-0.6b` | `mlx-community/Qwen3-0.6B-4bit@73e3e38d981303bc594367cd910ea6eb48349da8` | No |
| `minicpm5-2b` | `openbmb/MiniCPM5-2B-MLX@8a9ad7539ac86281d0ac2b017ba04a5de53fe9a3` | No |
| `qwen3.5-4b` | `mlx-community/Qwen3.5-4B-4bit@0e7ffd5c629ef7719d4cbc04069232580bfa9d9c` | No |

These are the repository's existing local options, not OpenJev's GGUF builds.
`rippletide setup --model ALIAS` installs an alternative;
`RIPPLETIDE_MODEL=ALIAS uv run rippletide serve` selects it. Each server keeps one
warm worker. `RIPPLETIDE_DATA_DIR` overrides the model data directory.

Cold loading waits up to 90 seconds, separately from the 60-second inference
limit. Candidate labels are distinct validated single tokens, including catalogs
larger than 26 tools. Requests exceeding token or label capacity fail explicitly.

The old `status`, `report`, project configuration, preference CLI and guard script
belong to the historical experiment harness. They are not exposed or invoked by
the active MCP selector. Installing this package into stock Codex alone does not
activate host selection.
