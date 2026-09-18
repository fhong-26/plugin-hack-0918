"""The host calls the local selector before exposing a tool schema to Codex."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from rippletide import __version__
from rippletide.identity import data_directory
from rippletide.model import WorkerManager
from rippletide.selection import Tool, select_tool


def create_server(worker=None, *, model: str | None = None) -> MCPServer:
    worker = worker if worker is not None else WorkerManager(data_directory(), model=model)

    @asynccontextmanager
    async def lifespan(server):
        worker.start(wait=False)
        try:
            yield
        finally:
            worker.close()

    server = MCPServer("rippletide", version=__version__, lifespan=lifespan)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    async def route(context: str, question: str, tools: list[Tool]) -> dict[str, Any]:
        """Select one supplied session tool using the local model. Host-only: Codex fills its arguments afterward. Errors stop selection; they never authorize a fallback."""
        # Cold startup is separate from the existing bounded inference deadline.
        ready = await asyncio.to_thread(worker.start, wait=True, timeout=90)
        if not ready:
            return {"status": "error", "reason_code": "MODEL_UNAVAILABLE"}
        return await asyncio.to_thread(
            select_tool, worker, context=context, question=question,
            tools=[tool.model_dump() for tool in tools],
        )

    return server


def serve(model: str | None = None):
    create_server(model=model).run(transport="stdio")
