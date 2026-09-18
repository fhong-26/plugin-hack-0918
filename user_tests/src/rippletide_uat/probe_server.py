"""Read-only host-hook preflight. Never registered during measured tasks."""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from typing import Any


def main() -> None:
    server = MCPServer(name="rippletide_uat_probe", version="1")

    @server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    def ping() -> dict[str, Any]:
        """Return a fixed readiness marker. No repository or remote data is read."""
        return {"ready": True, "purpose": "host_hook_preflight"}

    server.run()


if __name__ == "__main__":
    main()
