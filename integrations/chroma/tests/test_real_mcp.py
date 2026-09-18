import asyncio
import os

import pytest

from rippletide_semantic.cli import check_server
from rippletide_semantic.indexing import index_workspace


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RIPPLETIDE_SEMANTIC_INTEGRATION") != "1", reason="opt in to model download and real MCP test")
def test_real_semantic_query_and_refresh(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sessions.py").write_text(
        '"""Reject expired user sessions and log the user out."""\n'
        'def is_active(session, now):\n'
        '    return now < session["expires_at"]\n'
    )
    (workspace / "palette.py").write_text(
        '"""Return CSS colors for the button theme."""\n'
        'def colors():\n'
        '    return {"background": "blue", "foreground": "white"}\n'
    )
    data_dir = tmp_path / "chroma"
    assert index_workspace(workspace, data_dir, "test_sources")["chunk_count"] == 2
    result = asyncio.run(check_server(data_dir, "test_sources", "Where are outdated login credentials rejected?"))
    assert result["ready"] and result["mcp_verified"]
    assert result["result"]["metadatas"][0][0]["file"] == "sessions.py"
    assert result["result"]["metadatas"][0][0]["start_line"] == 1
    assert result["result"]["metadatas"][0][0]["end_line"] == 3
    old_id = result["result"]["ids"][0][0]
    palette = asyncio.run(check_server(data_dir, "test_sources", "How do we select the button's background color?"))
    assert palette["result"]["metadatas"][0][0]["file"] == "palette.py"
    (workspace / "sessions.py").write_text('"""Different content: session expiration is checked at login."""\n')
    assert index_workspace(workspace, data_dir, "test_sources")["chunk_count"] == 2
    refreshed = asyncio.run(check_server(data_dir, "test_sources", "Where are outdated login credentials rejected?"))
    assert old_id not in refreshed["result"]["ids"][0]
