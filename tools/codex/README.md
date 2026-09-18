# Codex host integration

The strict Jev architecture needs this patched Codex CLI. A plugin cannot replace
sampling-time tool selection in stock Codex Desktop or the packaged npm binary.
The patch is kept here so all three changes can be reviewed in this repository;
no upstream Codex fork or global installation is required.

## Build and run

Prerequisites: Git, Python 3, and the Rust toolchain requested by the pinned Codex
source (`rust-toolchain.toml`). From the repository root:

```sh
python3 tools/codex/build.py
build/codex-host/codex-rs/target/release/codex
```

Install/enable this repository's Rippletide plugin in that CLI (see the root
README). The matching strict plugin contract is required. The existing
`tools/codex/node_modules` binary remains the unmodified historical test host.

`build.py` pins `openai/codex` commit
`f0a1b8f0849d90960bc406b848f32e5a129b0457` (`rust-v0.155.0`), verifies the checkout,
and applies `jev.patch`. It does not reset existing source or modify global
Codex. The release tag leaves workspace package versions stale in Cargo.lock;
Cargo updates those local versions during the build. Third-party dependencies
remain from the checked-in lockfile. `--prepare-only` skips compilation.

## Behavior

With an enabled Rippletide MCP server, before each normal agent sampling request:

1. The host sends current instructions, conversation, latest user request, and
   every callable session tool's name/description to the local `route` operation.
   Deferred MCP tools and hosted web search participate; the selector's own
   management tools and disabled/hidden tools do not.
2. Jev returns one exact tool name. Failure stops the turn; it never restores
   LLM tool selection as a fallback.
3. The host exposes only that tool's full schema to Codex, with parallel calls
   disabled. Codex fills arguments and the existing runtime executes them.
   A dispatch check rejects different tools and repeated calls before another
   selection. Codex can still produce a final text answer without a tool call.

Without an enabled Rippletide server, Codex behavior is unchanged. Existing
approval, sandbox and MCP access controls remain in the execution path.

This is a source integration for the pinned CLI, not an injection into an
already-running Desktop app. The local model's context/candidate capacity and
inference errors are explicit failures, not silent truncation or fallback.

## Verify the patch

From `build/codex-host/codex-rs`, with `just` and `cargo-nextest` installed:

```sh
just test -p codex-core -E 'test(jev)'
```

The tests exercise native and MCP execution, hosted-tool schema selection,
namespace isolation, invalid selections before sampling, and one-use dispatch.
They use a deterministic MCP selector and mock Responses service so they test
host behavior independently from the local model's prediction quality.
