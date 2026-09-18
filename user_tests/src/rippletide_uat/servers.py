from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .storage import RecordStore, append_event, digest, read_json

READ_ANNOTATIONS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def create_server(kind: str, run: Path) -> MCPServer:
    if kind not in {"docs", "tracker"}:
        raise ValueError("server must be docs or tracker")
    manifest = read_json(run / "run.json")
    store = RecordStore(run / f"{kind}.sqlite3")
    server = MCPServer(name=f"uat_{kind}", version="0.1.0")

    def execute(tool: str, arguments: dict, action):
        start = time.monotonic()
        result = None
        status = "error"
        try:
            result = action()
            status = "success"
            return result
        finally:
            records = []
            if isinstance(result, dict):
                records = result.get("records", [result] if "id" in result else [])
            append_event(
                run / "tool-events.jsonl", manifest["run_id"], "tool_call",
                server=f"uat_{kind}", tool=tool, call_id=str(uuid.uuid4()),
                call_id_source="fixture_server", decision_id=arguments.get("decision_id"),
                status=status, argument_hash=digest(arguments), result_hash=digest(result),
                returned_record_ids=[row["id"] for row in records],
                elapsed_ms=round((time.monotonic() - start) * 1000, 3),
                phase=os.environ.get("RIPPLETIDE_UAT_PHASE", "task"),
            )

    if kind == "docs":
        @server.tool(structured_output=True, annotations=READ_ANNOTATIONS)
        def search_documents(query: str, project: str, limit: int = 5, decision_id: str | None = None) -> dict[str, Any]:
            """Search real project documentation, including version/status provenance. Fetch a record to read the full requirements. Projects: taskboard, session-alpha, session-beta."""
            arguments = {"query": query, "project": project, "limit": limit, "decision_id": decision_id}
            return execute("search_documents", arguments, lambda: {"records": store.search(query, project, limit)})

        @server.tool(structured_output=True, annotations=READ_ANNOTATIONS)
        def get_document(document_id: str, decision_id: str | None = None) -> dict[str, Any]:
            """Read a complete stored document by its returned document ID, including version, publication status, and stable source URI."""
            return execute("get_document", {"document_id": document_id, "decision_id": decision_id}, lambda: store.get(document_id))
    else:
        @server.tool(structured_output=True, annotations=READ_ANNOTATIONS)
        def search_issues(query: str, project: str, limit: int = 5, decision_id: str | None = None) -> dict[str, Any]:
            """Search real project issues, approved changes, and historical proposals. Inspect status/version and fetch complete issues. Projects: taskboard, session-alpha, session-beta."""
            arguments = {"query": query, "project": project, "limit": limit, "decision_id": decision_id}
            return execute("search_issues", arguments, lambda: {"records": store.search(query, project, limit)})

        @server.tool(structured_output=True, annotations=READ_ANNOTATIONS)
        def get_issue(issue_id: str, decision_id: str | None = None) -> dict[str, Any]:
            """Read a complete stored issue by its returned issue ID, including reproduction, approval status, and stable source URI."""
            return execute("get_issue", {"issue_id": issue_id, "decision_id": decision_id}, lambda: store.get(issue_id))
    return server
