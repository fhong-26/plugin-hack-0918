import json

import pytest

from rippletide.config import builtin_capabilities


def pytest_addoption(parser):
    parser.addoption("--run-model", action="store_true", help="Run real pinned MLX inference tests (requires rippletide setup)")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-model"):
        for item in items:
            if "model" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Pass --run-model after rippletide setup for real inference"))


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr("rippletide.config.global_preferences_path", lambda: tmp_path / "global-preferences.json")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = workspace / ".rippletide"
    directory.mkdir()
    caps = builtin_capabilities()
    for cap in caps:
        cap["available"] = True
    caps += [
        {
            "id": "mcp.semantic_search", "kind": "mcp", "operations": ["repository_search"],
            "description": "Find code by conceptual meaning when no exact identifier or filename is known.",
            "available": True, "invocation": {"server": "uat_semantic", "tool": "chroma_query_documents"},
            "input_schema": {"type": "object"},
        },
        {
            "id": "mcp.docs_search", "kind": "mcp", "operations": ["knowledge_lookup"],
            "description": "Search authoritative product specifications, requirements and design documentation.",
            "available": True, "invocation": {"server": "uat_docs", "tool": "search_documents"},
            "input_schema": {"type": "object"},
        },
        {
            "id": "mcp.tracker_search", "kind": "mcp", "operations": ["knowledge_lookup"],
            "description": "Search bug reports, incident tickets, issue status and reported reproduction steps.",
            "available": True, "invocation": {"server": "uat_tracker", "tool": "search_issues"},
            "input_schema": {"type": "object"},
        },
        {
            "id": "agent.reviewer", "kind": "agent", "operations": ["specialist_assignment"],
            "description": "Review a code change for correctness, regressions and maintainability; report findings.",
            "available": True, "invocation": {"agent_type": "rippletide_reviewer"},
            "input_schema": {"type": "object"},
        },
        {
            "id": "agent.test_specialist", "kind": "agent", "operations": ["specialist_assignment"],
            "description": "Identify missing regression tests and design or implement focused test cases for a code change.",
            "available": True, "invocation": {"agent_type": "rippletide_test_specialist"},
            "input_schema": {"type": "object"},
        },
    ]
    config = {"version": 1, "registry_version": "v1", "run_id": "unit-run", "variant": "C", "capabilities": caps}
    (directory / "config.json").write_text(json.dumps(config))
    return workspace


@pytest.fixture
def configure(project):
    def change(**patch):
        path = project / ".rippletide" / "config.json"
        config = json.loads(path.read_text())
        config.update(patch)
        path.write_text(json.dumps(config))
        return config
    return change
