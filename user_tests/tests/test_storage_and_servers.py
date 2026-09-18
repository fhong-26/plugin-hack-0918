import asyncio
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from rippletide_uat.prepare import ASSETS, server_command
from rippletide_uat.storage import RecordStore, read_events, read_json, seed_database, write_json


@pytest.fixture
def seeded_run(tmp_path):
    write_json(tmp_path / "run.json", {"run_id": "protocol-test"})
    records = read_json(ASSETS / "records.json")
    for kind in ("docs", "tracker"):
        seed_database(tmp_path / f"{kind}.sqlite3", records[kind])
    return tmp_path


def test_real_search_changes_with_query_and_scope(seeded_run):
    store = RecordStore(seeded_run / "docs.sqlite3")
    assert "DOC-SESSION-2" in {row["id"] for row in store.search("expiration", "session-alpha")}
    assert store.search("unfindablezzzz", "session-alpha") == []
    assert {row["id"] for row in store.search("expiration", "session-beta")} == {"DOC-BETA-1"}
    assert store.search("task tracker", "session-alpha") == []
    assert store.get("DOC-SESSION-2")["status"] == "published"
    with pytest.raises(ValueError):
        store.get("MISSING")
    with pytest.raises(ValueError):
        store.search("expiry", "session-alpha", 100)


@pytest.mark.parametrize("kind,search,fetch,id_key,record_id", [
    ("docs", "search_documents", "get_document", "document_id", "DOC-SESSION-2"),
    ("tracker", "search_issues", "get_issue", "issue_id", "SESSION-17"),
])
def test_real_stdio_protocol_search_fetch_error_and_logs(seeded_run, kind, search, fetch, id_key, record_id):
    async def exercise():
        async with Client(StdioServerParameters(**server_command(kind, seeded_run))) as client:
            listed = await client.list_tools()
            assert {search, fetch} == {tool.name for tool in listed.tools}
            assert all(tool.annotations.read_only_hint and tool.annotations.idempotent_hint and tool.annotations.destructive_hint is False and tool.annotations.open_world_hint is False for tool in listed.tools)
            result = await client.call_tool(search, {"query": "session deadline expiration", "project": "session-alpha", "decision_id": "unit-protocol-decision"})
            assert not result.is_error
            assert record_id in result.model_dump_json()
            absent = await client.call_tool(search, {"query": "unfindablezzzz", "project": "session-alpha"})
            assert absent.structured_content == {"records": []}
            full = await client.call_tool(fetch, {id_key: record_id})
            assert not full.is_error
            assert "body" in full.structured_content
            error = await client.call_tool(fetch, {id_key: "MISSING"})
            assert error.is_error
    asyncio.run(exercise())
    events = read_events(seeded_run / "tool-events.jsonl")
    assert len(events) == 4
    assert events[0]["decision_id"] == "unit-protocol-decision"
    assert record_id in events[0]["returned_record_ids"]
    assert events[-1]["status"] == "error"
    assert all(event["elapsed_ms"] >= 0 and event["run_id"] == "protocol-test" for event in events)
