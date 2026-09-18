"""Real-model contract checks, distinct from end-user Codex acceptance tests."""

import pytest

from rippletide.identity import ENGINE_REVISION, WEIGHTS_REVISION, data_directory
from rippletide.model import WorkerManager
from rippletide.router import Router

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def model_worker():
    worker = WorkerManager(data_directory())
    assert worker.start(wait=True), worker.status()
    yield worker
    worker.close()


@pytest.mark.parametrize("operation,goal,acceptable", [
    ("knowledge_lookup", "Find the authoritative current requirements and product specification for session expiration.", {"mcp.docs_search"}),
    ("knowledge_lookup", "Find the bug ticket reporting expired sessions remaining active, including its reproduction steps.", {"mcp.tracker_search"}),
    ("specialist_assignment", "Assign a specialist to identify missing regression tests and implement test cases for this patch.", {"agent.test_specialist"}),
    ("specialist_assignment", "Assign a specialist to review this patch for correctness and regressions and report code review findings.", {"agent.reviewer"}),
    ("repository_search", "Locate the function that rejects an expired session; I do not know its identifier or filename.", {"mcp.semantic_search", "native.lexical_search"}),
])
def test_actual_model_decisions(model_worker, project, configure, operation, goal, acceptable):
    configure(variant="D")
    router = Router(worker=model_worker)
    before = model_worker.status()["pid"]
    result = router.route(project_root=str(project), operation=operation, goal=goal)
    assert result["status"] == "selected", result
    assert result["source"] == "model", result
    assert result["route_id"] in acceptable, result
    assert result["worker_pid"] == before == model_worker.status()["pid"]
    assert result["input_tokens"] <= 1024
    assert result["elapsed_ms"] <= 2000
    identity = router.status(str(project))["model_identity"]
    assert identity["engine_revision"] == ENGINE_REVISION
    assert identity["weights_revision"] == WEIGHTS_REVISION


def test_real_tokenizer_drops_old_observations_before_essentials(model_worker, project, configure):
    configure(variant="D")
    router = Router(worker=model_worker)
    result = router.route(project_root=str(project), operation="knowledge_lookup", goal="Find authoritative session-expiration requirements in the documentation", recent_observations=[{"detail": "irrelevant " * 3000}, {"detail": "short recent observation"}])
    assert result["source"] == "model", result
    assert result["input_tokens"] <= 1024
    assert result["observations_used"] == 1
    oversized = router.route(project_root=str(project), operation="knowledge_lookup", goal="essential " * 3000)
    assert oversized["reason_code"] == "CONTEXT_TOO_LARGE"
    assert oversized["input_tokens"] > 1024


def test_actual_model_repeatability_and_worker_reuse(model_worker, project, configure):
    configure(variant="D")
    router = Router(worker=model_worker)
    packets = [router.route(project_root=str(project), operation="knowledge_lookup", goal="Find the authoritative current session-expiration product requirements") for _ in range(5)]
    assert all(result["source"] == "model" for result in packets), packets
    assert len({result["route_id"] for result in packets}) == 1
    assert len({result["worker_pid"] for result in packets}) == 1
