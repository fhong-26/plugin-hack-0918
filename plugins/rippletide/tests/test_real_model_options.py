"""Opt-in actual load/readout tests; correctness is recorded, not manufactured."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rippletide.catalog import MODELS
from rippletide.identity import data_directory
from rippletide.model import WorkerManager
from rippletide.router import Router

pytestmark = pytest.mark.model


@pytest.mark.parametrize("alias", MODELS)
def test_all_pinned_models_load_reuse_and_bound_real_decisions(alias, project, configure):
    configure(variant="D")
    worker = WorkerManager(data_directory(), model=alias)
    evidence = {"model": alias, "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "developer_real_model_contract", "not_user_acceptance": True, "decisions": []}
    try:
        assert worker.start(wait=True), worker.status()
        evidence["worker"] = worker.status()
        assert evidence["worker"]["model_identity"]["weights_revision"] == MODELS[alias].revision
        router = Router(worker=worker, model=alias)
        cases = [
            ("repository_search", "Find the exact text validate_identity inside the repository source files.", {"native.lexical_search"}),
            ("knowledge_lookup", "Find the published project specification for the current session expiration policy.", {"mcp.docs_search"}),
            ("knowledge_lookup", "Find the reported expired-session bug ticket and its reproduction steps.", {"mcp.tracker_search"}),
            ("specialist_assignment", "Assign a specialist to review this patch for correctness and regressions and report code review findings.", {"agent.reviewer"}),
            ("specialist_assignment", "Assign a specialist to identify missing regression tests and implement test cases for this patch.", {"agent.test_specialist"}),
        ]
        for operation, goal, acceptable in cases:
            result = router.route(project_root=str(project), operation=operation, goal=goal)
            evidence["decisions"].append({"operation": operation, "goal": goal, "result": result,
                "acceptable_routes": sorted(acceptable), "correct": result.get("route_id") in acceptable})
            assert result["reason_code"] == "MODEL_SELECTION", result
            assert result["input_tokens"] <= 1024 and result["elapsed_ms"] <= 2000
            assert result["worker_pid"] == evidence["worker"]["pid"]
            assert result["score_kind"] == "uncalibrated_candidate_softmax"
        assert any(item["result"]["status"] == "selected" for item in evidence["decisions"])
        operation, goal, _ = cases[1]
        repeated = [router.route(project_root=str(project), operation=operation, goal=goal) for _ in range(3)]
        evidence["repeatability"] = repeated
        assert len({(item["status"], item["route_id"]) for item in repeated}) == 1
        assert all(item["worker_pid"] == evidence["worker"]["pid"] for item in repeated)
        oversized = router.route(project_root=str(project), operation=operation, goal="essential " * 3000)
        assert oversized["reason_code"] == "CONTEXT_TOO_LARGE", oversized
        trimmed = router.route(project_root=str(project), operation=operation, goal=goal,
            recent_observations=[{"detail": "irrelevant " * 3000}, {"detail": "short recent observation"}])
        assert trimmed["observations_used"] == 1 and trimmed["input_tokens"] <= 1024
        evidence.update(status="passed", oversized=oversized, trimmed=trimmed)
    except BaseException as exc:
        evidence.update(status="failed", error=str(exc))
        raise
    finally:
        worker.close()
        if output := os.environ.get("RIPPLETIDE_MODEL_EVIDENCE_DIR"):
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{alias}-{uuid.uuid4().hex[:8]}.json").write_text(json.dumps(evidence, indent=2) + "\n")
