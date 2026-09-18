"""The three public MCP operations, implemented with the official SDK."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from rippletide import __version__
from rippletide.router import Router


def create_server(router: Router | None = None) -> MCPServer:
    router = router or Router()

    @asynccontextmanager
    async def lifespan(server):
        router.worker.start(wait=False)
        try:
            yield {"router": router}
        finally:
            router.close()

    server = MCPServer(
        "rippletide", version=__version__, lifespan=lifespan,
        instructions="Recommend registered capabilities for immediate tasks. Codex executes the selected tool or agent. A defer means continue independently; do not repeatedly request the same decision.",
    )

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
    async def route(
        project_root: str,
        goal: str = "",
        operation: str = "",
        facts: dict[str, Any] | None = None,
        recent_observations: list[dict[str, Any]] | None = None,
        preferred_route: str | None = None,
    ) -> dict[str, Any]:
        """Choose one available registered tool or specialist; log an advisory decision locally. No target execution. Supply the immediate goal, compact facts and at most two observations, without enumerating tools."""
        return await asyncio.to_thread(
            router.route, goal=goal, operation=operation, facts=facts or {},
            recent_observations=recent_observations or [], project_root=project_root,
            preferred_route=preferred_route,
        )

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    async def status(project_root: str) -> dict[str, Any]:
        """Inspect readiness, pinned model identities, registered capabilities and data paths. Do not route this tool."""
        return await asyncio.to_thread(router.status, project_root)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    async def report(project_root: str, limit: int = 20) -> dict[str, Any]:
        """Summarize local recommendations and their measured routing times. Execution remains unknown without host/tool evidence. Do not route this tool."""
        return await asyncio.to_thread(router.report, project_root, limit)

    return server


def serve():
    create_server().run(transport="stdio")
