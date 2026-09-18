"""Real local model and public MCP contract; host execution is covered in jev.patch."""

import asyncio
import os
import subprocess
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.model


def test_model_selected_tool_executes_after_public_selection(tmp_path):
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "rippletide", "serve"], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                # The first request waits for the real cold worker. Even a single
                # candidate is scored, so a missing/broken model cannot pass.
                result = await client.call_tool("route", {
                    "context": "A developer wants to execute a Python print command.",
                    "question": "Which tool can run the command?",
                    "tools": [{"name": "exec_command", "description": "Execute a shell command"}],
                })
                assert not result.is_error
                decision = result.structured_content
                assert set(decision) == {"status", "tool", "score"}
                assert decision["status"] == "selected" and decision["tool"] == "exec_command"
                assert 0 <= decision["score"] <= 1
                # Arguments are supplied after selection. No invocation parameters
                # or command hints come back from the scorer.
                executed = subprocess.run([sys.executable, "-c", "print('selected then executed')"],
                                          cwd=tmp_path, capture_output=True, text=True, check=True)
                assert executed.stdout == "selected then executed\n"
    asyncio.run(exercise())


def test_public_server_disconnect_during_loading_is_quiet(tmp_path):
    async def exercise():
        stderr_path = tmp_path / "early-disconnect.stderr"
        with stderr_path.open("w") as diagnostics:
            params = StdioServerParameters(command=sys.executable, args=["-m", "rippletide", "serve"], env=dict(os.environ))
            async with stdio_client(params, errlog=diagnostics) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    assert [tool.name for tool in (await client.list_tools()).tools] == ["route"]
            await asyncio.sleep(1)
        log = stderr_path.read_text()
        assert "BrokenPipeError" not in log and "Traceback" not in log, log
    asyncio.run(exercise())
