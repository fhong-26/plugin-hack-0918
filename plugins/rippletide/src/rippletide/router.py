"""Rule-first advisory routing. This module never executes recommended targets."""

import json
import hashlib
import math
import os
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rippletide.artifacts import read_artifacts, supported_platform
from rippletide.config import ProjectConfig, is_available, load_config
from rippletide.catalog import model_spec
from rippletide.identity import ROUTE_TIMEOUT_SECONDS, data_directory, model_identity
from rippletide.model import WorkerManager


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal: str = ""
    operation: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)
    recent_observations: list[dict[str, Any]] = Field(default_factory=list, max_length=2)
    project_root: str
    preferred_route: str | None = None


def log_path(config: ProjectConfig, root: Path) -> Path:
    if run_dir := os.environ.get("RIPPLETIDE_RUN_DIR"):
        return Path(run_dir).expanduser().resolve() / "router-events.jsonl"
    path = Path(config.log_path).expanduser() if config.log_path else root / ".rippletide" / "decisions.jsonl"
    return path if path.is_absolute() else root / path


def bounded_context(value: dict, limit: int = 32768) -> dict:
    """Retain exact normal routing context; mark oversized rejected input honestly."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(serialized.encode("utf-8")) <= limit:
        return {"value": value, "truncated": False}
    return {"value": None, "truncated": True, "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "preview": serialized.encode()[:limit].decode("utf-8", errors="ignore")}


def append_event(path: Path, event: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = (json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n").encode()
    # An advisory file lock keeps entire JSONL lines intact across processes.
    import fcntl
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "ab", buffering=0) as stream:
        # A competing writer must not make routing wait beyond its deadline.
        # If busy, the response explicitly reports log_error instead of claiming a trace was saved.
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            stream.write(line)
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Router:
    def __init__(self, *, data_dir: Path | None = None, worker=None, model: str | None = None):
        self.data_dir = data_dir or data_directory()
        self.model = model_spec(model if model is not None else getattr(worker, "model", None)).alias
        if worker is not None and getattr(worker, "model", self.model) != self.model:
            raise ValueError("Configured router model does not match supplied worker")
        self.worker = worker if worker is not None else WorkerManager(self.data_dir, model=self.model)

    def route(self, **parameters) -> dict:
        started = time.perf_counter()
        config = ProjectConfig()
        project_root = parameters.get("project_root")
        root = Path(project_root).expanduser().resolve() if isinstance(project_root, str) and project_root else None
        decision_id = str(uuid.uuid4())
        request = None
        candidates = []

        def finish(reason: str, *, selected=None, source="fallback", diagnostics=None):
            response = {
                "decision_id": decision_id, "status": "selected" if selected else "defer",
                "route_id": selected.id if selected else None, "source": source,
                "reason_code": reason, "registry_version": config.registry_version,
                "invocation": selected.invocation if selected else None,
                "input_schema": selected.input_schema if selected else None,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
            if diagnostics:
                for key in ("score", "score_kind", "input_tokens", "observations_used", "inference_ms", "worker_pid", "worker_state", "prompt_version", "prompt_sha256", "output_tokens", "readout_tokens", "label", "label_token_id"):
                    if key in diagnostics:
                        response[key] = diagnostics[key]
            summary = {
                "goal": request.goal[:256] if request else None,
                "operation": request.operation if request else None,
                "project_root": str(root) if root else None,
                "preferred_route": request.preferred_route if request else None,
                "fact_keys": sorted(request.facts) if request else [],
                "observation_count": len(request.recent_observations) if request else 0,
            }
            if root and root.is_dir():
                try:
                    context = bounded_context(request.model_dump() if request else {})
                    catalog = bounded_context({"candidates": [{"id": cap.id, "kind": cap.kind,
                        "description": cap.description, "invocation": cap.invocation} for cap in candidates]})
                    append_event(log_path(config, root), {
                        "schema_version": 1, "event": "routing_decision",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "run_id": os.environ.get("RIPPLETIDE_RUN_ID") or config.run_id, "response": response,
                        "phase": os.environ.get("RIPPLETIDE_PHASE", config.phase),
                        "request_summary": summary, "request": context["value"],
                        "request_capture": {key: value for key, value in context.items() if key != "value"},
                        "candidates": catalog["value"]["candidates"] if catalog["value"] is not None else None,
                        "candidate_capture": {key: value for key, value in catalog.items() if key != "value"},
                        "model_identity": model_identity(self.model),
                        "elapsed_ms": response["elapsed_ms"], "variant": config.variant,
                        "actual_execution": "unknown",
                    })
                except (OSError, ValueError) as exc:
                    response["log_error"] = str(exc)
            return response

        try:
            request = Request.model_validate(parameters)
            if not request.goal.strip() or not request.operation.strip():
                return finish("INVALID_REQUEST")
            config, preferences, root = load_config(request.project_root)
        except (ValidationError, ValueError, OSError) as exc:
            return finish("INVALID_REQUEST" if request is None else "CONFIG_ERROR")

        if config.variant in {"A", "B"}:
            return finish("ROUTER_DISABLED")
        registered_operations = {operation for cap in config.capabilities for operation in cap.operations}
        if request.operation not in registered_operations | {"repository_search", "knowledge_lookup", "specialist_assignment"}:
            return finish("UNSUPPORTED_OPERATION")
        candidates = [cap for cap in config.capabilities
            if request.operation in cap.operations and is_available(cap) and cap.id not in preferences.exclude]
        by_id = {cap.id: cap for cap in candidates}
        failed = {
            item.get("route_id") for item in request.recent_observations
            if item.get("outcome") in {"no_matches", "error", "failed", "unavailable", "timeout"}
        }
        preferred = request.preferred_route or preferences.prefer.get(request.operation)
        if preferred:
            if preferred not in by_id:
                return finish("PREFERRED_ROUTE_UNAVAILABLE", source="rule")
            if preferred in failed:
                return finish("PREFERRED_ROUTE_PREVIOUSLY_FAILED", source="rule")
            reason = "TASK_PREFERENCE" if request.preferred_route else "SAVED_PREFERENCE"
            return finish(reason, selected=by_id[preferred], source="rule")
        candidates = [cap for cap in candidates if cap.id not in failed]
        by_id = {cap.id: cap for cap in candidates}
        if not candidates:
            return finish("NO_AVAILABLE_CANDIDATES", source="rule")
        if request.operation == "repository_search":
            if isinstance(request.facts.get("exact_symbol"), str) and request.facts["exact_symbol"].strip() and preferences.exact_symbol_first:
                if cap := by_id.get("native.lexical_search"):
                    return finish("EXACT_SYMBOL", selected=cap, source="rule")
            if isinstance(request.facts.get("filename"), str) and request.facts["filename"].strip():
                if cap := by_id.get("native.filename_search"):
                    return finish("KNOWN_FILENAME", selected=cap, source="rule")
        if len(candidates) == 1:
            return finish("ONLY_CANDIDATE", selected=candidates[0], source="rule")
        if config.variant == "C":
            return finish("RULES_ONLY_UNRESOLVED", source="rule")
        if len(candidates) > 25:
            return finish("TOO_MANY_CANDIDATES")
        # Sorting preserves label assignment for equal registries, regardless of JSON order.
        candidates.sort(key=lambda cap: cap.id)
        packet = {
            "goal": request.goal, "operation": request.operation, "facts": request.facts,
            "recent_observations": request.recent_observations,
            "candidates": [{"id": cap.id, "kind": cap.kind, "description": cap.description} for cap in candidates],
        }
        remaining = ROUTE_TIMEOUT_SECONDS - (time.perf_counter() - started)
        if remaining <= 0:
            return finish("ROUTER_TIMEOUT")
        try:
            result = self.worker.predict(packet, timeout=remaining)
        except Exception:
            return finish("MODEL_ERROR")
        if not isinstance(result, dict):
            return finish("INVALID_MODEL_OUTPUT")
        if time.perf_counter() - started > ROUTE_TIMEOUT_SECONDS:
            return finish("ROUTER_TIMEOUT", diagnostics=result)
        score = result.get("score")
        if score is not None and (not isinstance(score, (float, int)) or not math.isfinite(score) or not 0 <= score <= 1):
            return finish("INVALID_MODEL_OUTPUT")
        if result.get("status") == "selected":
            route_id = result.get("route_id")
            if not isinstance(route_id, str):
                return finish("INVALID_MODEL_OUTPUT")
            cap = by_id.get(route_id)
            if not cap:
                return finish("INVALID_MODEL_OUTPUT")
            return finish("MODEL_SELECTION", selected=cap, source="model", diagnostics=result)
        if result.get("status") != "defer":
            return finish("INVALID_MODEL_OUTPUT")
        reason = result.get("reason_code", "MODEL_ERROR")
        known_reasons = {"MODEL_ERROR", "MODEL_CRASH", "MODEL_NOT_READY", "ROUTER_TIMEOUT", "CONTEXT_TOO_LARGE", "LABEL_TOKEN_COLLISION", "TOO_MANY_CANDIDATES", "INVALID_MODEL_OUTPUT"}
        if reason not in known_reasons:
            reason = "INVALID_MODEL_OUTPUT"
        return finish(reason, diagnostics=result)

    def status(self, project_root: str) -> dict:
        errors = []
        configuration_valid = True
        try:
            config, preferences, root = load_config(project_root)
            capabilities = [cap.model_dump(exclude_none=True) for cap in config.capabilities]
            available = [cap.id for cap in config.capabilities if is_available(cap) and cap.id not in preferences.exclude]
            path = str(log_path(config, root))
        except (ValueError, OSError) as exc:
            config, capabilities, available, path = ProjectConfig(), [], [], None
            configuration_valid = False
            errors.append(str(exc))
        try:
            artifacts = read_artifacts(self.data_dir, model=self.model)
            installed = True
        except (ValueError, OSError, KeyError) as exc:
            artifacts, installed = {}, False
            errors.append(str(exc))
        worker = self.worker.status()
        return {
            "ready": configuration_valid and bool(available) and (config.variant == "C" or worker["ready"]),
            "routing_available": bool(available) and config.variant in {"C", "D"},
            "variant": config.variant, "registry_version": config.registry_version,
            "platform_supported": supported_platform(), "model_installed": installed,
            "model_identity": model_identity(self.model), "worker": worker,
            "supported_capabilities": capabilities, "available_capabilities": available,
            "paths": {"data_dir": str(self.data_dir), "source": artifacts.get("source_path"), "weights": artifacts.get("weights_path"), "log": path},
            "errors": errors,
        }

    def report(self, project_root: str, limit: int = 20) -> dict:
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            return {"error": "limit must be between 1 and 1000"}
        try:
            config, _, root = load_config(project_root)
        except (ValueError, OSError) as exc:
            return {"error": str(exc)}
        path = log_path(config, root)
        recent = deque(maxlen=limit)
        by_source, by_status, by_reason = Counter(), Counter(), Counter()
        malformed = count = 0
        total_ms = 0.0
        try:
            with path.open() as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict) or event.get("event") != "routing_decision":
                            continue
                        response = event["response"]
                        count += 1
                        by_source[response["source"]] += 1
                        by_status[response["status"]] += 1
                        by_reason[response["reason_code"]] += 1
                        total_ms += float(response["elapsed_ms"])
                        recent.append({**response, "actual_execution": "unknown"})
                    except (ValueError, KeyError, TypeError):
                        malformed += 1
        except FileNotFoundError:
            pass
        except OSError as exc:
            return {"error": str(exc), "log_path": str(path)}
        return {
            "log_path": str(path), "decisions": count, "by_source": dict(by_source),
            "by_status": dict(by_status), "by_reason": dict(by_reason),
            "mean_routing_ms": round(total_ms / count, 3) if count else None,
            "malformed_lines": malformed, "recent": list(recent),
            "actual_execution": "unknown",
            "note": "Recommendations are not execution evidence. Correlate the Codex session and tool-event records to verify calls or overrides.",
        }

    def close(self):
        self.worker.close()
