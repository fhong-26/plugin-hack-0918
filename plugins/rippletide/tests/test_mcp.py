import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_mcp_contract(project, tmp_path):
    async def exercise():
        env = dict(os.environ, RIPPLETIDE_DATA_DIR=str(tmp_path / "missing-model"))
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "rippletide", "serve"], env=env)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"route", "status", "report"}
                annotations = {tool.name: tool.annotations for tool in tools.tools}
                assert annotations["route"].read_only_hint is False
                assert annotations["status"].read_only_hint is True
                assert annotations["report"].read_only_hint is True
                for annotation in annotations.values():
                    assert annotation.destructive_hint is False
                    assert annotation.open_world_hint is False
                result = await session.call_tool("route", {"goal": "Find session function", "operation": "repository_search", "facts": {"exact_symbol": "session"}, "project_root": str(project)})
                assert not result.is_error
                assert result.structured_content["route_id"] == "native.lexical_search"
                status = await session.call_tool("status", {"project_root": str(project)})
                assert status.structured_content["variant"] == "C"
                report = await session.call_tool("report", {"project_root": str(project)})
                assert report.structured_content["decisions"] == 1
                assert report.structured_content["actual_execution"] == "unknown"
    asyncio.run(exercise())
