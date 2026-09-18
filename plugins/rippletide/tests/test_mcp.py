import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_mcp_contract(tmp_path):
    async def exercise():
        env = dict(os.environ, RIPPLETIDE_DATA_DIR=str(tmp_path / "missing-model"))
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "rippletide", "serve"], env=env)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                assert [tool.name for tool in listing.tools] == ["route"]
                tool = listing.tools[0]
                assert set(tool.input_schema["properties"]) == {"context", "question", "tools"}
                assert set(tool.input_schema["required"]) == {"context", "question", "tools"}
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.open_world_hint is False
                result = await session.call_tool("route", {
                    "context": "The user is working in a repository.",
                    "question": "Which tool should run next?",
                    "tools": [{"name": "exec_command", "description": "Run a shell command"}],
                })
                assert not result.is_error
                assert result.structured_content == {"status": "error", "reason_code": "MODEL_UNAVAILABLE"}
    asyncio.run(exercise())
