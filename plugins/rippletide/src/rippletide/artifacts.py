"""Download and verify the requested engine and its declared weights dependency."""

import hashlib
import json
import platform
from pathlib import Path

from rippletide.catalog import DEFAULT_MODEL, model_spec
from rippletide.identity import (
    ENGINE_ID, ENGINE_REVISION, SOURCE_FILES, model_identity,
)


def supported_platform() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def artifact_manifest(data_dir: Path, alias: str | None = None) -> Path:
    spec = model_spec(alias)
    # Retain the installed v1 manifest and weight cache without migration.
    return data_dir / "artifacts.json" if spec.alias == DEFAULT_MODEL else data_dir / "models" / spec.alias / "artifacts.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_small_artifacts(directory: Path, repository: str, revision: str, names: list[str]) -> dict:
    """Verify cached source/tokenizer bytes against the immutable commit's metadata."""
    from huggingface_hub import HfApi
    info = HfApi().model_info(repository, revision=revision, files_metadata=True)
    if info.sha != revision:
        raise RuntimeError(f"Repository did not resolve to pinned revision: {repository}")
    files = {entry.rfilename: entry for entry in info.siblings}
    result = {}
    for name in names:
        entry = files.get(name)
        if entry is None:
            raise RuntimeError(f"Unexpected artifact in pinned snapshot: {name}")
        contents = (directory / name).read_bytes()
        digest = hashlib.sha256(contents).hexdigest()
        if entry.lfs:
            verified = digest == entry.lfs.sha256
        else:
            blob = b"blob " + str(len(contents)).encode() + b"\0" + contents
            verified = hashlib.sha1(blob).hexdigest() == entry.blob_id
        if not verified:
            raise RuntimeError(f"Pinned source/configuration checksum mismatch: {name}")
        result[name] = digest
    return result


def read_artifacts(data_dir: Path, *, verify_source: bool = False, model: str | None = None) -> dict:
    spec = model_spec(model)
    manifest = artifact_manifest(data_dir, spec.alias)
    data = json.loads(manifest.read_text())
    identity = model_identity(spec.alias)
    # New descriptive/runtime fields must not invalidate a valid v1 install.
    for key in ("engine_id", "engine_revision", "weights_id", "weights_revision", "backend", "temperature"):
        value = identity[key]
        if data.get(key) != value:
            raise ValueError(f"Model identity mismatch: {key}; rerun rippletide setup")
    weights = Path(data["weights_path"])
    if spec.adapter == "rlcd":
        source = Path(data["source_path"])
        for name in SOURCE_FILES:
            file = source / name
            if not file.is_file():
                raise ValueError(f"Missing engine source: {name}")
            if verify_source and sha256_file(file) != data["source_sha256"].get(name):
                raise ValueError(f"Engine source changed: {name}; rerun rippletide setup")
    for name in ("config.json", "tokenizer.json", "model.safetensors"):
        if not (weights / name).is_file():
            raise ValueError(f"Missing model artifact: {name}")
    if data.get("weights_sha256") != spec.weights_sha256:
        raise ValueError("Pinned weights checksum identity mismatch; rerun rippletide setup")
    if verify_source:
        # The large weights are checked at setup; startup verifies all config and
        # tokenizer files, so a changed chat template cannot silently alter behavior.
        for name, expected in data.get("artifact_sha256", {}).items():
            if not name.endswith(".safetensors") and sha256_file(weights / name) != expected:
                raise ValueError(f"Model configuration changed: {name}; rerun rippletide setup")
    return data


def setup_artifacts(data_dir: Path, model: str | None = None) -> dict:
    if not supported_platform():
        raise RuntimeError("This pilot requires Apple Silicon macOS; no alternative backend is selected")
    from huggingface_hub import snapshot_download

    spec = model_spec(model)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache = str(data_dir / "hub")
    source = (Path(snapshot_download(ENGINE_ID, revision=ENGINE_REVISION, cache_dir=cache, allow_patterns=list(SOURCE_FILES)))
              if spec.adapter == "rlcd" else None)
    weights = Path(snapshot_download(spec.weights_id, revision=spec.revision, cache_dir=cache,
        allow_patterns=["*.json", "*.safetensors", "*.jinja", "*.txt"]))
    if sha256_file(weights / "model.safetensors") != spec.weights_sha256:
        raise RuntimeError("Pinned model.safetensors checksum mismatch")
    source_sha256 = verify_small_artifacts(source, ENGINE_ID, ENGINE_REVISION, list(SOURCE_FILES)) if source else {}
    names = [file.name for file in weights.iterdir() if file.is_file() and file.suffix in {".json", ".jinja", ".txt"}]
    artifact_sha256 = verify_small_artifacts(weights, spec.weights_id, spec.revision, names)
    data = {
        **model_identity(spec.alias), "source_path": str(source) if source else None, "weights_path": str(weights),
        "weights_sha256": spec.weights_sha256,
        "source_sha256": source_sha256, "artifact_sha256": artifact_sha256,
    }
    manifest = artifact_manifest(data_dir, spec.alias)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(manifest)
    return data
