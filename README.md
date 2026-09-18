# Rippletide

Rippletide is a planned Codex plugin that uses explicit preferences and a small local model to choose tools for recurring coding tasks. Codex handles task reasoning, generates tool arguments, executes tools, and interprets results.

**Status:** Product planning. This repository currently contains documentation; the plugin, model integration, and evaluation harness have not been implemented.

## Start here

- [Product requirements](PRD.md): scope, user flow, routing behavior, test cases, definition of done, and proposed success criteria.
- [Original ChatGPT response](chatgpt-response-prd-source.md): preserved source material for the product discussion.

## First version

The MVP helps Codex choose between filename/path search, exact-text search, and an available semantic-search integration. Developers configure project preferences, work normally in Codex, and can inspect or correct routing decisions.

The proposed flow is:

1. Codex sends an immediate search goal and relevant observations to Rippletide.
2. Rippletide checks tool availability and applies explicit preferences.
3. If rules do not settle the choice, the small model selects an allowed route or defers.
4. Codex receives the recommendation, supplies the tool arguments, and continues the task.

The router falls back to Codex when it cannot decide or is unavailable. It recommends tools through an explicit handoff; the MVP does not replace Codex's internal tool-selection process.

## Small model and integration

The required backend is [harshatheg/Qwen-2.5-1B-RLCD](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD). The PRD records the project's documented MLX configuration using `mlx-community/Qwen2.5-1.5B-Instruct-4bit`. Verifying runnable artifacts and pinning engine and weight revisions are part of the first implementation milestone.

The planned initial platform is local Apple Silicon macOS. The plugin will package a routing skill and a Python router exposed through MCP. Installation commands will be added once that implementation exists.

## Development milestones

1. Verify the required backend and one complete Codex routing handoff.
2. Implement search routes, preferences, rules, model decisions, fallback, and local traces.
3. Compare Codex alone, routing instructions, rules-only routing, and rules plus the small model.

Faster execution, lower token usage, and more consistent choices are goals to measure. The [PRD](PRD.md) defines proposed targets and distinguishes a completed implementation from a validated product. Fine-tuning and RL are later work.
