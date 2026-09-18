"""Public process interface; does not import router or user-test-kit internals."""

import argparse
import asyncio
from contextlib import redirect_stdout
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from .indexing import index_workspace


DEFAULT_COLLECTION = "rippletide_workspace"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def launch_config(data_dir: Path) -> dict[str, Any]:
    """Launch the official package's entry point with its locked dependency set."""
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("uv must be installed and on PATH")
    return {
        "command": uv,
        "args": ["run", "--locked", "--project", str(PROJECT_ROOT), "chroma-mcp",
                 "--client-type", "persistent", "--data-dir", str(data_dir.resolve()),
                 "--dotenv-path", os.devnull],
        "env": {"ANONYMIZED_TELEMETRY": "False"},
    }


async def check_server(data_dir: Path, collection_name: str, query: str, *, timeout: float = 60) -> dict[str, Any]:
    """Query through the real upstream STDIO MCP server, never a replacement server."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    config = launch_config(data_dir)
    params = StdioServerParameters(**config)
    async with asyncio.timeout(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                query_tool = next((tool for tool in tools.tools if tool.name == "chroma_query_documents"), None)
                if query_tool is None:
                    raise RuntimeError("upstream server does not expose chroma_query_documents")
                response = await session.call_tool("chroma_query_documents", {
                    "collection_name": collection_name,
                    "query_texts": [query],
                    "n_results": 3,
                    "include": ["documents", "metadatas", "distances"],
                })
                if response.isError:
                    raise RuntimeError("; ".join(block.text for block in response.content if hasattr(block, "text")))
                body = json.loads(next(block.text for block in response.content if hasattr(block, "text")))
                ids = body.get("ids", [[]])[0]
                if not ids:
                    raise RuntimeError("semantic query returned no indexed chunks")
                return {
                    "ready": True,
                    "mcp_verified": True,
                    "server": "uat_semantic",
                    "tool": query_tool.name,
                    "collection_name": collection_name,
                    "input_schema": query_tool.inputSchema,
                    "query": query,
                    "result": body,
                    "server_config": config,
                    "versions": {name: version(name) for name in ("chroma-mcp", "chromadb", "mcp")},
                }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="Index workspace source and verify actual MCP search")
    index.add_argument("--workspace", type=Path, required=True)
    index.add_argument("--data-dir", type=Path, required=True)
    index.add_argument("--collection", default=DEFAULT_COLLECTION)
    check = commands.add_parser("check", help="Verify existing index with a real upstream MCP query")
    check.add_argument("--data-dir", type=Path, required=True)
    check.add_argument("--collection", default=DEFAULT_COLLECTION)
    check.add_argument("--query", default="Where is session expiration enforced?")
    check.add_argument("--timeout", type=float, default=60)
    config = commands.add_parser("config", help="Print launch configuration without claiming readiness")
    config.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        with redirect_stdout(sys.stderr):
            if args.command == "config":
                result = {"ready": False, "reason": "NOT_CHECKED", "server": "uat_semantic",
                          "server_config": launch_config(args.data_dir)}
            elif args.command == "check":
                result = asyncio.run(check_server(args.data_dir, args.collection, args.query, timeout=args.timeout))
            else:
                result = index_workspace(args.workspace, args.data_dir, args.collection)
                if result["indexed"]:
                    result.update(asyncio.run(check_server(args.data_dir, args.collection, "Find the code that implements this project")))
        print(json.dumps(result, ensure_ascii=False))
        if not result.get("ready") and args.command != "config":
            sys.exit(1)
    except Exception as exc:
        def describe(error: BaseException) -> str:
            if isinstance(error, BaseExceptionGroup):
                return "; ".join(describe(child) for child in error.exceptions)
            return f"{type(error).__name__}: {error}"

        print(json.dumps({"ready": False, "mcp_verified": False, "reason": "SEMANTIC_UNAVAILABLE", "error": describe(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
