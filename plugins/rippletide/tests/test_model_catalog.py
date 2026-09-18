import json
import hashlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rippletide.artifacts import artifact_manifest, read_artifacts, verify_small_artifacts
from rippletide.catalog import DEFAULT_MODEL, MODELS, model_spec
from rippletide.direct_logit import messages_for, prepare_input, validated_label_ids
from rippletide.identity import ENGINE_REVISION, SOURCE_FILES, model_identity
from rippletide.model import WorkerManager
from rippletide.router import Router, bounded_context


def test_process_model_defaults_and_explicit_override(monkeypatch, tmp_path):
    monkeypatch.delenv("RIPPLETIDE_MODEL", raising=False)
    assert model_spec().alias == DEFAULT_MODEL
    assert model_identity()["engine_revision"] == ENGINE_REVISION
    monkeypatch.setenv("RIPPLETIDE_MODEL", "minicpm5-2b")
    worker = WorkerManager(tmp_path)
    assert worker.model == "minicpm5-2b"
    assert WorkerManager(tmp_path, "qwen25-rlcd").model == DEFAULT_MODEL
    monkeypatch.setenv("RIPPLETIDE_MODEL", "qwen3.5-4b")
    assert worker.model == "minicpm5-2b", "A running server cannot silently change models"
    assert worker.status()["model_identity"]["weights_id"] == MODELS["minicpm5-2b"].weights_id
    with pytest.raises(ValueError, match="does not match"):
        Router(worker=worker, model="qwen3.5-4b")
    with pytest.raises(ValueError, match="Unknown router model"):
        WorkerManager(tmp_path, "silently-fallback")


@pytest.mark.parametrize("alias", MODELS)
def test_artifact_paths_and_backward_compatible_manifest(tmp_path, alias):
    weights = tmp_path / "weights"
    weights.mkdir()
    for name in ("config.json", "tokenizer.json", "model.safetensors"):
        (weights / name).write_text("test artifact")
    source = tmp_path / "source"
    for name in SOURCE_FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# test source")
    identity = model_identity(alias)
    legacy_fields = ("engine_id", "engine_revision", "weights_id", "weights_revision", "backend", "temperature")
    manifest = {key: identity[key] for key in legacy_fields}
    manifest.update(weights_path=str(weights), source_path=str(source), weights_sha256=MODELS[alias].weights_sha256)
    path = artifact_manifest(tmp_path, alias)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    assert (path == tmp_path / "artifacts.json") is (alias == DEFAULT_MODEL)
    assert read_artifacts(tmp_path, model=alias)["weights_revision"] == MODELS[alias].revision
    manifest["weights_revision"] = "wrong-revision"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity mismatch"):
        read_artifacts(tmp_path, model=alias)


def test_tokenizer_validates_whole_single_token_labels():
    class Tokenizer:
        def encode(self, label, **_):
            return [ord(label)]

        def decode(self, ids):
            return chr(ids[0])

    assert validated_label_ids(Tokenizer())["Z"] == ord("Z")
    bad = Tokenizer()
    bad.encode = lambda *_, **__: [42, 43]
    with pytest.raises(ValueError, match="one-token"):
        validated_label_ids(bad)
    bad.encode = lambda *_, **__: [42]
    with pytest.raises(ValueError, match="distinct"):
        validated_label_ids(bad)


def test_chat_template_and_budget_drop_observations_not_essentials():
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == {"tokenize": True, "add_generation_prompt": True, "enable_thinking": False}
            assert '"important": "remain"' in messages[-1]["content"]
            return list(range(len(messages[-1]["content"])))

    packet = {"goal": "Find a requirement", "facts": {"important": "remain"},
        "candidates": [{"description": "Read documents"}, {"description": "Read issues"}],
        "recent_observations": [{"detail": "x" * 3000}, {"detail": "most recent"}]}
    tokens, observations = prepare_input(Tokenizer(), packet)
    assert len(tokens) < 1024 and observations == packet["recent_observations"][1:]
    assert "Z: Defer" in messages_for(packet, observations)[1]["content"]
    packet["goal"] = "x" * 2000
    tokens, observations = prepare_input(Tokenizer(), packet)
    assert len(tokens) > 1024 and not observations


def test_run_scoped_evidence_records_actual_bounded_context(project, configure, monkeypatch, tmp_path):
    run = tmp_path / "evidence"
    monkeypatch.setenv("RIPPLETIDE_RUN_DIR", str(run))
    monkeypatch.setenv("RIPPLETIDE_RUN_ID", "paired-enabled")
    configure(phase="preflight")
    router = Router(data_dir=tmp_path / "absent", model="qwen3-0.6b")
    result = router.route(project_root=str(project), goal="Find the file", operation="repository_search",
        facts={"filename": "session.py", "project": "alpha"}, recent_observations=[{"detail": "no stale draft"}])
    event = json.loads((run / "router-events.jsonl").read_text())
    assert event["phase"] == "preflight" and event["run_id"] == "paired-enabled"
    assert event["model_identity"]["model"] == "qwen3-0.6b"
    assert event["request"]["facts"] == {"filename": "session.py", "project": "alpha"}
    assert event["request"]["recent_observations"] == [{"detail": "no stale draft"}]
    assert event["request_capture"] == {"truncated": False}
    assert result["source"] == "rule"
    assert router.report(str(project))["decisions"] == 1
    oversized = bounded_context({"goal": "x" * 40000})
    assert oversized["truncated"] and oversized["value"] is None and len(oversized["preview"]) <= 32768
    assert not (project / ".rippletide" / "decisions.jsonl").exists()


def test_cli_models_is_non_loading_and_exposes_all_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLETIDE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RIPPLETIDE_MODEL", raising=False)
    result = subprocess.run([sys.executable, "-m", "rippletide", "models"], capture_output=True, text=True, check=True)
    listed = json.loads(result.stdout)
    assert listed["default"] == DEFAULT_MODEL
    assert {item["model"] for item in listed["models"]} == set(MODELS)
    assert not any(item["installed"] for item in listed["models"])
    assert not list(tmp_path.iterdir()), "Listing model options must not download or create artifacts"


def test_uninstalled_alternative_never_silently_loads_default(tmp_path, project):
    router = Router(data_dir=tmp_path, model="minicpm5-2b")
    assert router.worker.start(wait=True) is False
    status = router.status(str(project))
    assert status["model_identity"]["model"] == "minicpm5-2b"
    assert status["model_installed"] is False
    assert status["worker"]["state"] == "unavailable" and status["worker"]["pid"] is None
    assert status["worker"]["model_identity"]["model"] == "minicpm5-2b"


def test_artifact_config_tampering_is_detected_before_loading(tmp_path):
    alias = "qwen3-0.6b"
    weights = tmp_path / "weights"
    weights.mkdir()
    for name in ("config.json", "tokenizer.json", "model.safetensors"):
        (weights / name).write_text("changed")
    path = artifact_manifest(tmp_path, alias)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**model_identity(alias), "weights_path": str(weights),
        "weights_sha256": MODELS[alias].weights_sha256, "artifact_sha256": {"tokenizer.json": "wrong-checksum"}}))
    with pytest.raises(ValueError, match="Model configuration changed: tokenizer.json"):
        read_artifacts(tmp_path, model=alias, verify_source=True)


def test_routing_payload_cannot_override_process_model(tmp_path, project):
    router = Router(data_dir=tmp_path, model="qwen3-0.6b")
    result = router.route(project_root=str(project), goal="Find file", operation="repository_search",
        model="minicpm5-2b")
    assert result["reason_code"] == "INVALID_REQUEST"
    assert router.model == "qwen3-0.6b"


def test_invalid_environment_model_reports_configuration_error(monkeypatch):
    monkeypatch.setenv("RIPPLETIDE_MODEL", "not-a-supported-model")
    result = subprocess.run([sys.executable, "-m", "rippletide", "serve"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Unknown router model" in result.stderr and "Traceback" not in result.stderr


def test_setup_checks_configuration_against_pinned_commit(tmp_path, monkeypatch):
    contents = b"fixed tokenizer"
    path = tmp_path / "tokenizer.json"
    path.write_bytes(contents)
    blob_id = hashlib.sha1(b"blob " + str(len(contents)).encode() + b"\0" + contents).hexdigest()
    info = SimpleNamespace(sha="immutable", siblings=[SimpleNamespace(rfilename="tokenizer.json", lfs=None, blob_id=blob_id)])
    monkeypatch.setattr("huggingface_hub.HfApi.model_info", lambda *_, **__: info)
    checksums = verify_small_artifacts(tmp_path, "test/model", "immutable", ["tokenizer.json"])
    assert checksums["tokenizer.json"] == hashlib.sha256(contents).hexdigest()
    path.write_text("tampered cached tokenizer")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        verify_small_artifacts(tmp_path, "test/model", "immutable", ["tokenizer.json"])
