"""Opt-in, local preference memory and a small learned residual routing policy.

The profile is process configuration, never a routing-tool argument. Learning
consumes explicit corrections, not silent acceptance or model self-labels.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Iterator

VERSION = 1
MODES = ("off", "memory", "residual", "lora")


def default_profile_path() -> Path:
    if value := os.environ.get("RIPPLETIDE_PROFILE"):
        return Path(value).expanduser().resolve()
    return Path(os.environ.get("RIPPLETIDE_DATA_DIR", "~/.local/share/rippletide")).expanduser().resolve() / "profile"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def exclusive(path: Path) -> Iterator[None]:
    """OS-owned nonblocking lock; process exit releases it even after a crash."""
    from rippletide.portable import lock_file, unlock_file
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        lock_file(fd)
        acquired = True
        yield
    finally:
        if acquired:
            unlock_file(fd)
        os.close(fd)


def init_profile(path: Path, *, user_id: str, preferences: list[str],
                 learn: bool = False, auto_train: bool = False, mode: str = "memory") -> dict:
    if mode not in MODES or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user_id):
        raise ValueError("Invalid mode or user identifier")
    if type(learn) is not bool or type(auto_train) is not bool:
        raise ValueError("Learning settings must be explicit JSON booleans")
    if auto_train and not learn:
        raise ValueError("Automatic training requires learning to be enabled")
    if not isinstance(preferences, list) or len(preferences) > 8 or any(not isinstance(x, str) or not 1 <= len(x) <= 240 for x in preferences):
        raise ValueError("Use at most eight preferences, each 1–240 characters")
    path.mkdir(parents=True, exist_ok=True)
    with exclusive(path / ".profile.lock"):
        if (path / "profile.json").exists():
            raise ValueError("Profile exists; use configure to update it")
        profile = {"version": VERSION, "user_id": user_id, "mode": mode,
                   "preferences": preferences, "learning_enabled": learn,
                   "auto_train": auto_train, "minimum_examples": 40,
                   "created_at": datetime.now(timezone.utc).isoformat()}
        atomic_json(path / "profile.json", profile)
        atomic_json(path / "feedback.json", [])
    return profile


def configure_profile(path: Path, **changes) -> dict:
    allowed = {"mode", "preferences", "learning_enabled", "auto_train", "minimum_examples"}
    if set(changes) - allowed:
        raise ValueError("Unknown profile settings")
    with exclusive(path / ".profile.lock"):
        profile = read_json(path / "profile.json")
        profile.update(changes)
        if type(profile["learning_enabled"]) is not bool or type(profile["auto_train"]) is not bool:
            raise ValueError("Learning settings must be explicit JSON booleans")
        if profile["mode"] not in MODES or type(profile["minimum_examples"]) is not int or not 10 <= profile["minimum_examples"] <= 100000:
            raise ValueError("Invalid learning configuration")
        if profile["auto_train"] and not profile["learning_enabled"]:
            raise ValueError("Automatic training requires learning consent")
        if not isinstance(profile["preferences"], list) or len(profile["preferences"]) > 8 or any(not isinstance(x, str) or not 1 <= len(x) <= 240 for x in profile["preferences"]):
            raise ValueError("Invalid preferences")
        atomic_json(path / "profile.json", profile)
        return profile


def record_feedback(path: Path, event: dict, preferred_route: str, *, family_id: str,
                    source: str = "explicit_user", explanation: str = "") -> dict:
    if source != "explicit_user":
        raise ValueError("Only explicit user corrections may become preference labels")
    if not family_id or len(family_id) > 160:
        raise ValueError("A bounded scenario family is required for leakage-safe splitting")
    request, candidates = event.get("request"), event.get("candidates")
    decision = event.get("response", {}).get("decision_id")
    if not isinstance(request, dict) or not candidates or not decision:
        raise ValueError("A complete recorded decision is required")
    if preferred_route not in {x["id"] for x in candidates} | {"defer"}:
        raise ValueError("Correction must name a candidate from this decision, or defer")
    packet = {key: request.get(key, {} if key == "facts" else [])
              for key in ("goal", "operation", "facts", "recent_observations")}
    packet["candidates"] = [{k: c[k] for k in ("id", "description", "kind") if k in c} for c in candidates]
    with exclusive(path / ".profile.lock"):
        profile = read_json(path / "profile.json")
        if not profile["learning_enabled"]:
            raise ValueError("Learning is disabled; enable it explicitly before collecting corrections")
        records = read_json(path / "feedback.json")
        if any(x["decision_id"] == decision for x in records):
            raise ValueError("A correction for this decision is already recorded")
        record = {"decision_id": decision, "family_id": family_id, "packet": packet,
                  "preferred_route": preferred_route, "source": source,
                  "explanation": explanation[:240], "user_id": profile["user_id"],
                  "timestamp": datetime.now(timezone.utc).isoformat()}
        records.append(record)
        atomic_json(path / "feedback.json", records)
    return {"saved": True, "examples": len(records), "decision_id": decision,
            "training_eligible": profile["auto_train"] and len(records) >= profile["minimum_examples"]}


def words(value: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]{2,}", value.lower()))


def relevant_memory(packet: dict, records: list[dict], preferences: list[str], limit: int = 3) -> dict:
    query = words(packet["goal"] + " " + json.dumps(packet.get("facts", {})))
    eligible = {c["id"] for c in packet["candidates"]} | {"defer"}
    ranked = []
    for record in records:
        previous = record["packet"]
        if previous["operation"] != packet["operation"] or record["preferred_route"] not in eligible:
            continue
        text = words(previous["goal"] + " " + json.dumps(previous.get("facts", {})))
        similarity = len(query & text) / max(1, len(query | text))
        ranked.append((similarity, record["decision_id"], record))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return {"preferences": preferences, "examples": [
        {"goal": row["packet"]["goal"][:200], "preferred_capability": row["preferred_route"],
         "reason": row.get("explanation", "")[:160]}
        for _, _, row in ranked[:limit]]}


def memory_text(memory: dict, candidates: list[dict], labels: list[str]) -> str:
    mapping = {cap["id"]: label for cap, label in zip(candidates, labels)}
    converted = {"preferences": memory.get("preferences", []), "examples": []}
    for example in memory.get("examples", []):
        route = example["preferred_capability"]
        if route in mapping:
            converted["examples"].append({"previous_need": example["goal"],
                                         "preferred_option": mapping[route], "reason": example.get("reason", "")})
    if not any(converted.values()):
        return ""
    return "\nUser routing preferences and past corrections (apply only when relevant; current task and availability take precedence):\n" + json.dumps(converted, ensure_ascii=False)


def features(packet: dict, candidate: dict) -> dict[str, float]:
    """Candidate descriptions let a learned policy transfer to renamed tools."""
    operation = packet.get("operation", "")
    context = words(packet["goal"] + " " + json.dumps(packet.get("facts", {}), sort_keys=True))
    cap_words = words(candidate.get("description", ""))
    values = {"intercept": 1.0, "op:" + operation: 1.0}
    for term in cap_words:
        values["cap:" + term] = 1.0 / max(1, len(cap_words)) ** 0.5
        values[f"op:{operation}|cap:{term}"] = 1.0 / max(1, len(cap_words)) ** 0.5
        for token in context:
            values[f"ctx:{token}|cap:{term}"] = 1.0 / max(1, len(context) * len(cap_words)) ** 0.5
    return values


def softmax(values: list[float]) -> list[float]:
    if not values or any(not math.isfinite(v) for v in values):
        raise ValueError("Candidate scores must be finite and nonempty")
    maximum = max(values)
    weights = [math.exp(v - maximum) for v in values]
    total = sum(weights)
    return [v / total for v in weights]


def adjusted_scores(packet: dict, logits: list[float], policy: dict | None) -> list[float]:
    candidates = packet["candidates"] + [{"id": "defer", "description": "Defer unclear unsupported task"}]
    if len(candidates) != len(logits):
        raise ValueError("Scores must include every candidate and defer")
    if not policy:
        return list(logits)
    coefficients = policy["weights"]
    limit = float(policy.get("max_adjustment", 4.0))
    return [score + max(-limit, min(limit, sum(coefficients.get(k, 0.0) * v
                                             for k, v in features(packet, cap).items())))
            for cap, score in zip(candidates, logits)]


def train_residual(rows: list[dict], *, epochs: int = 30, rate: float = 0.3,
                   regularization: float = 0.001, seed: int = 31) -> dict:
    import random
    if not rows:
        raise ValueError("Training data is empty")
    rng = random.Random(seed)
    policy = {"version": VERSION, "weights": {}, "max_adjustment": 4.0,
              "training_digest": digest(rows), "epochs": epochs, "seed": seed}
    prepared = []
    for row in rows:
        packet = row["packet"]
        candidates = packet["candidates"] + [{"id": "defer", "description": "Defer unclear unsupported task"}]
        target = [c["id"] for c in candidates].index(row["preferred_route"])
        logits = row["candidate_logits"]
        if len(logits) != len(candidates):
            raise ValueError("Training logits do not match candidates")
        prepared.append((row, target, [features(packet, c) for c in candidates]))
    for _ in range(epochs):
        rng.shuffle(prepared)
        for row, target, vectors in prepared:
            probabilities = softmax(adjusted_scores(row["packet"], row["candidate_logits"], policy))
            gradient = Counter()
            for index, vector in enumerate(vectors):
                error = probabilities[index] - (index == target)
                for key, value in vector.items():
                    gradient[key] += error * value
            for key, value in gradient.items():
                old = policy["weights"].get(key, 0.0)
                policy["weights"][key] = old - rate * (value + regularization * old)
    return policy


class Personalizer:
    """Read a frozen profile snapshot for one model-worker lifetime."""

    def __init__(self, path: Path | None = None, *, enabled: bool = True):
        default = default_profile_path()
        selected = (path or (default if (default / "profile.json").exists() else None)) if enabled else None
        self.path = Path(selected).expanduser().resolve() if selected else None
        self.profile = read_json(self.path / "profile.json") if self.path else {"mode": "off"}
        self.records = read_json(self.path / "feedback.json") if self.path else []
        self.active = read_json(self.path / "active.json") if self.path and (self.path / "active.json").exists() else None
        self.policy = None
        self.adapter_path = None
        if self.active and self.profile["mode"] == self.active["mode"] and self.profile["mode"] in {"residual", "lora"}:
            artifact = (self.path / self.active["artifact"]).resolve()
            if not artifact.is_relative_to(self.path):
                raise ValueError("Personalization artifact escapes its profile")
            if self.profile["mode"] == "residual":
                self.policy = read_json(artifact)
                if digest(self.policy) != self.active["artifact_digest"]:
                    raise ValueError("Residual policy checksum mismatch")
            else:
                manifest = read_json(artifact / "rippletide_adapter.json")
                if digest(manifest) != self.active["artifact_digest"]:
                    raise ValueError("LoRA manifest checksum mismatch")
                for filename, expected in manifest["files"].items():
                    file = (artifact / filename).resolve()
                    if not file.is_relative_to(artifact) or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                        raise ValueError("LoRA artifact checksum mismatch")
                self.adapter_path = artifact

    def packet(self, packet: dict) -> dict:
        if self.profile["mode"] == "off":
            return packet
        memory = relevant_memory(packet, self.records, self.profile.get("preferences", []), limit=1)
        # Every personalized arm receives the same information; training is the
        # extra treatment, not privileged access to user preferences.
        return {**packet, "preference_memory": memory}

    def identity(self) -> dict:
        return {"mode": self.profile["mode"], "profile_digest": digest(self.profile),
                "history_digest": digest(self.records), "active": self.active,
                "adapter_loaded": self.adapter_path is not None}

    def validate_base(self, identity: dict, backend: str) -> None:
        if (self.policy is not None or self.adapter_path is not None) and (self.active["base_identity"] != identity or self.active["backend"] != backend):
            raise ValueError("Personalization artifact belongs to another base model/backend")


def activate(path: Path, *, mode: str, artifact: Path, base_identity: dict, backend: str,
             validation: dict) -> dict:
    """Only evaluated candidates can be promoted; preserve the previous version."""
    if mode not in {"residual", "lora"} or validation.get("passed") is not True:
        raise ValueError("Activation requires a passing held-out validation record")
    root, artifact = path.resolve(), artifact.resolve()
    if not artifact.is_relative_to(root):
        raise ValueError("Place the versioned artifact inside the profile before activation")
    content = read_json(artifact if mode == "residual" else artifact / "rippletide_adapter.json")
    if mode == "lora" and (content["base_identity"] != base_identity or content["backend"] != backend):
        raise ValueError("LoRA manifest belongs to another base model/backend")
    record = {"version": VERSION, "mode": mode, "artifact": str(artifact.relative_to(root)),
              "artifact_digest": digest(content), "base_identity": base_identity,
              "backend": backend, "validation": validation,
              "activated_at": datetime.now(timezone.utc).isoformat()}
    with exclusive(root / ".profile.lock"):
        if (root / "active.json").exists():
            atomic_json(root / "previous.json", read_json(root / "active.json"))
        else:
            atomic_json(root / "previous.json", None)
        atomic_json(root / "active.json", record)
        profile = read_json(root / "profile.json")
        profile["mode"] = mode
        atomic_json(root / "profile.json", profile)
    return record


def rollback(path: Path) -> dict:
    with exclusive(path / ".profile.lock"):
        previous = read_json(path / "previous.json")
        current = read_json(path / "active.json")
        atomic_json(path / "active.json", previous)
        atomic_json(path / "previous.json", current)
        profile = read_json(path / "profile.json")
        profile["mode"] = previous["mode"] if previous else "memory"
        atomic_json(path / "profile.json", profile)
    return {"restored": previous, "restart_worker": True}
