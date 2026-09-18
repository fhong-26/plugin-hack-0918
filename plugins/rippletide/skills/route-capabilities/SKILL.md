---
name: route-capabilities
description: Use Rippletide's host-selected tool and generate its arguments when working with the patched Codex CLI and the Rippletide plugin.
---

# Rippletide tool selection

The patched Codex host calls the local Jev selector with the current context,
request, and complete available tool catalog before each tool decision. It then
exposes only the selected tool's schema to you.

Fill that tool's arguments for the user's task, execute it, and interpret its
result. Keep normal approval and sandbox requirements. A selection is not proof
of execution or task success. You may provide a final text answer when no further
tool use is needed.

Do not call `route` yourself, invent a candidate shortlist, override the selected
tool, or substitute another tool after a selection error. Surface the error.

This workflow requires the patched CLI described in `tools/codex/README.md` in
the source repository. Installing the plugin in stock Codex does not replace
Codex's internal tool selection. If the host exposes the full catalog and expects
you to call `route`, report the missing host integration.
