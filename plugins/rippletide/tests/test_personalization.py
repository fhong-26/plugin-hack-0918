import copy
import json
from pathlib import Path

import pytest

from rippletide.personalization import (Personalizer, init_profile, configure_profile, record_feedback,
    relevant_memory, train_residual, adjusted_scores, softmax, atomic_json, activate, rollback, digest)


def packet():
    return {"goal": "Investigate unfamiliar cache behavior", "operation": "repository_search", "facts": {},
            "recent_observations": [], "candidates": [
                {"id": "lexical", "description": "Search exact keywords in source code"},
                {"id": "semantic", "description": "Search code by conceptual behavior"}]}


def event(identity="d1"):
    value = packet()
    return {"response": {"decision_id": identity}, "request": {k: v for k, v in value.items() if k != "candidates"},
            "candidates": value["candidates"]}


def test_feedback_requires_prior_opt_in_and_real_decision(tmp_path):
    init_profile(tmp_path, user_id="a", preferences=[])
    with pytest.raises(ValueError, match="disabled"):
        record_feedback(tmp_path, event(), "semantic", family_id="cache")
    configure_profile(tmp_path, learning_enabled=True)
    with pytest.raises(ValueError, match="explicit user"):
        record_feedback(tmp_path, event(), "semantic", family_id="cache", source="successful_tool")
    with pytest.raises(ValueError, match="candidate"):
        record_feedback(tmp_path, event(), "unregistered", family_id="cache")
    record_feedback(tmp_path, event(), "semantic", family_id="cache")
    with pytest.raises(ValueError, match="already"):
        record_feedback(tmp_path, event(), "lexical", family_id="cache")
    assert len(Personalizer(tmp_path).records) == 1


def test_two_profiles_do_not_share_corrections_and_off_does_not_modify_input(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        init_profile(root, user_id=root.name, preferences=[], learn=True)
    record_feedback(a, event(), "semantic", family_id="cache")
    assert Personalizer(a).packet(packet())["preference_memory"]["examples"]
    assert not Personalizer(b).packet(packet())["preference_memory"]["examples"]
    configure_profile(a, mode="off")
    assert Personalizer(a).packet(packet()) == packet()


def test_memory_filters_other_operations_and_unavailable_candidates():
    record = {"decision_id": "x", "packet": packet(), "preferred_route": "semantic"}
    target = packet()
    target["candidates"] = target["candidates"][:1]
    assert not relevant_memory(target, [record], [])["examples"]
    target = packet()
    target["operation"] = "specialist_assignment"
    assert not relevant_memory(target, [record], [])["examples"]


def test_residual_training_changes_preference_and_is_equivariant_to_candidates():
    rows = [{"packet": packet(), "candidate_logits": [1.0, 0.0, -5.0], "preferred_route": "semantic"}] * 12
    policy = train_residual(rows)
    scores = softmax(adjusted_scores(packet(), rows[0]["candidate_logits"], policy))
    assert scores[1] > scores[0]
    shuffled = packet()
    shuffled["candidates"].reverse()
    other = softmax(adjusted_scores(shuffled, [0.0, 1.0, -5.0], policy))
    assert other == pytest.approx([scores[1], scores[0], scores[2]])
    renamed = packet()
    renamed["candidates"][0]["id"] = "new_search_id"
    assert adjusted_scores(renamed, [1, 0, -5], policy) == adjusted_scores(packet(), [1, 0, -5], policy)


def test_activation_validation_integrity_and_rollback(tmp_path):
    init_profile(tmp_path, user_id="a", preferences=[])
    one = tmp_path / "versions/one.json"
    two = tmp_path / "versions/two.json"
    atomic_json(one, {"weights": {}, "max_adjustment": 4})
    atomic_json(two, {"weights": {"cap:semantic": 1.0}, "max_adjustment": 4})
    with pytest.raises(ValueError, match="passing"):
        activate(tmp_path, mode="residual", artifact=one, base_identity={}, backend="torch", validation={"passed": False})
    activate(tmp_path, mode="residual", artifact=one, base_identity={}, backend="torch", validation={"passed": True})
    activate(tmp_path, mode="residual", artifact=two, base_identity={}, backend="torch", validation={"passed": True})
    assert Personalizer(tmp_path).policy["weights"]
    rollback(tmp_path)
    assert not Personalizer(tmp_path).policy["weights"]
    with pytest.raises(ValueError, match="another base"):
        Personalizer(tmp_path).validate_base({"different": True}, "torch")
    atomic_json(one, {"weights": {"tampered": 1}})
    with pytest.raises(ValueError, match="checksum"):
        Personalizer(tmp_path)


def test_profile_paths_cannot_escape_the_user_directory(tmp_path):
    root = tmp_path / "profile"
    init_profile(root, user_id="a", preferences=[])
    configure_profile(root, mode="residual")
    atomic_json(root / "active.json", {"mode": "residual", "artifact": "../outside.json"})
    with pytest.raises(ValueError, match="escapes"):
        Personalizer(root)


def test_first_activation_can_rollback_to_memory_and_disable_can_switch_base(tmp_path):
    init_profile(tmp_path, user_id="a", preferences=["Prefer semantic search"])
    artifact = tmp_path / "versions/first.json"
    atomic_json(artifact, {"weights": {}, "max_adjustment": 4})
    activate(tmp_path, mode="residual", artifact=artifact, base_identity={}, backend="torch", validation={"passed": True})
    rollback(tmp_path)
    assert Personalizer(tmp_path).profile["mode"] == "memory"
    assert Personalizer(tmp_path).policy is None
    rollback(tmp_path)
    assert Personalizer(tmp_path).policy is not None
    configure_profile(tmp_path, mode="off")
    Personalizer(tmp_path).validate_base({"another_model": True}, "mlx")


def test_os_lock_is_reusable_and_released_on_process_exit(tmp_path):
    import subprocess
    import sys
    from rippletide.personalization import exclusive
    lock = tmp_path / ".training.lock"
    with exclusive(lock):
        with pytest.raises(OSError):
            with exclusive(lock):
                pass
    code = "from pathlib import Path; import os,sys; from rippletide.personalization import exclusive\nwith exclusive(Path(sys.argv[1])): os._exit(0)"
    subprocess.run([sys.executable, "-c", code, str(lock)], check=True)
    with exclusive(lock):
        pass


def test_learning_consent_cannot_be_enabled_by_truthy_strings(tmp_path):
    init_profile(tmp_path, user_id="a", preferences=[])
    for changes in ({"learning_enabled": "false"}, {"auto_train": "true"},
                    {"minimum_examples": True}, {"preferences": "search"}):
        with pytest.raises(ValueError):
            configure_profile(tmp_path, **changes)
    assert Personalizer(tmp_path).profile["learning_enabled"] is False


def test_training_identity_changes_with_preferences_or_method():
    from rippletide.learning import training_input_digest
    profile = {"preferences": ["Prefer semantic"]}
    first = training_input_digest(profile, [], "qwen", "residual")
    assert first != training_input_digest(profile, [], "qwen", "lora")
    assert first != training_input_digest({"preferences": ["Prefer lexical"]}, [], "qwen", "residual")


def training_fixture(path, monkeypatch):
    from rippletide import torch_engine
    init_profile(path, user_id="a", preferences=[], learn=True)
    configure_profile(path, minimum_examples=10)
    records = []
    counts = {"train": 0, "validation": 0}
    index = 0
    while counts["train"] < 12 or counts["validation"] < 6:
        family = f"family-{index}"
        split = "validation" if int(digest(family)[:8], 16) % 5 == 0 else "train"
        index += 1
        if counts[split] >= (12 if split == "train" else 6):
            continue
        counts[split] += 1
        records.append({"decision_id": family, "family_id": family, "packet": packet(),
            "preferred_route": "semantic", "source": "explicit_user", "user_id": "a"})
    atomic_json(path / "feedback.json", records)
    class FrozenScores:
        def __init__(self, *args, **kwargs):
            pass
        def predict(self, value):
            return {"status": "selected", "route_id": "lexical", "reason_code": "MODEL_SELECTION",
                    "candidate_logits": [1.0, 0.0, -5.0], "candidate_ids": ["lexical", "semantic", "defer"]}
    monkeypatch.setattr(torch_engine, "TorchEngine", FrozenScores)


def test_training_gate_compares_the_incumbent_not_only_untrained_memory(tmp_path, monkeypatch):
    from rippletide.learning import train_profile
    training_fixture(tmp_path, monkeypatch)
    first = train_profile(tmp_path, "qwen3-0.6b-torch")
    assert first["status"] == "activated"
    assert first["validation"]["baseline"]["matched"] == 0
    assert first["validation"]["candidate"]["matched"] == 6
    active = Personalizer(tmp_path).active
    second = train_profile(tmp_path, "qwen3-0.6b-torch")
    assert second["status"] == "rejected"
    assert second["validation"]["incumbent"]["matched"] == 6
    assert Personalizer(tmp_path).active == active


def test_revoking_learning_during_training_prevents_activation(tmp_path, monkeypatch):
    from rippletide import learning
    training_fixture(tmp_path, monkeypatch)
    original = learning.train_residual
    def revoke(*args, **kwargs):
        policy = original(*args, **kwargs)
        configure_profile(tmp_path, learning_enabled=False)
        return policy
    monkeypatch.setattr(learning, "train_residual", revoke)
    with pytest.raises(ValueError, match="changed during training"):
        learning.train_profile(tmp_path, "qwen3-0.6b-torch")
    assert Personalizer(tmp_path).active is None
