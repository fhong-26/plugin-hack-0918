# Local semantic search for user tests

This package indexes a fixture workspace and launches the unmodified official
[`chroma-mcp`](https://github.com/chroma-core/chroma-mcp) server. Chroma performs
the vector indexing and search. Its default `all-MiniLM-L6-v2` embedding model
runs locally through ONNX; the first index downloads that model. No cloud
embedding service or API key is used.

The environment deliberately pins `chroma-mcp==0.2.6`, `chromadb==1.0.16`, and
`mcp==1.6.0`, separately from Rippletide's MCP 2 runtime. `uv.lock` pins transitive
dependencies. Run commands from this repository's root:

```sh
uv sync --locked --project integrations/chroma
uv run --locked --project integrations/chroma rippletide-semantic index \
  --workspace /absolute/run/workspace --data-dir /absolute/run/chroma
uv run --locked --project integrations/chroma rippletide-semantic check \
  --data-dir /absolute/run/chroma --query 'Where are expired sessions rejected?'
```

`index` reads source and documentation files, creates overlapping line chunks,
and stores content plus relative `file`, one-based inclusive `start_line` and
`end_line`, and `file_sha256` metadata. Hidden/configuration directories,
dependency/build directories, symlinks, binary files, and files over 128 KiB are
excluded. Keep graders outside the supplied workspace. Rerunning `index`
refreshes only the collection this integration created for that workspace,
removing its stale chunks; unrelated collections are rejected and never cleared.
Use a fresh data directory for each acceptance attempt.

Both commands print JSON to stdout. Diagnostics go to stderr. `index` reports
`ready: true` only after embedding succeeds **and** an actual STDIO MCP
initialize/list-tools/query roundtrip succeeds. Missing model, download errors,
empty workspaces, and protocol errors return `ready: false` with a nonzero exit.
An initially empty new project cannot pass semantic preflight; index it after
source exists. The config-only command makes no readiness claim.

The result includes `server_config`, ready to insert under
`mcp_servers.uat_semantic` in project `.codex/config.toml`:

```toml
[mcp_servers.uat_semantic]
command = "/absolute/path/to/uv"
args = ["run", "--locked", "--project", "/absolute/repo/integrations/chroma", "chroma-mcp", "--client-type", "persistent", "--data-dir", "/absolute/run/chroma", "--dotenv-path", "/dev/null"]
env = { ANONYMIZED_TELEMETRY = "False" }
```

Get the actual paths with `rippletide-semantic config --data-dir PATH`. The
route `mcp.semantic_search` targets server `uat_semantic`, tool
`chroma_query_documents`. Its call includes:

```json
{
  "collection_name": "rippletide_workspace",
  "query_texts": ["Where are expired sessions rejected?"],
  "n_results": 3,
  "include": ["documents", "metadatas", "distances"]
}
```

`index` and `check` return the actual discovered `input_schema`. This upstream
tool has no `decision_id` argument; use Codex session call events to correlate
execution, and leave ambiguous matches unverified. The upstream server exposes
collection mutation tools too; the router registry registers only query search.

```sh
uv run --locked --directory integrations/chroma pytest
RIPPLETIDE_SEMANTIC_INTEGRATION=1 uv run --locked --directory integrations/chroma pytest -m integration -q
```

The opt-in test embeds distinct live fixture content, starts the real MCP server,
checks that a semantic paraphrase ranks the session file first, verifies line
metadata, then changes the source and verifies the refreshed index.
