"""Download and verify the requested engine and its declared weights dependency."""

import hashlib
import json
import platform
from pathlib import Path

from rippletide.identity import (
    ENGINE_ID, ENGINE_REVISION, SOURCE_FILES, WEIGHTS_ID, WEIGHTS_REVISION,
    WEIGHTS_SHA256, model_identity,
)


def supported_platform() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def read_artifacts(data_dir: Path, *, verify_source: bool = False) -> dict:
    manifest = data_dir / "artifacts.json"
    data = json.loads(manifest.read_text())
    for key, value in model_identity().items():
        if data.get(key) != value:
            raise ValueError(f"Model identity mismatch: {key}; rerun rippletide setup")
    source = Path(data["source_path"])
    weights = Path(data["weights_path"])
    for name in SOURCE_FILES:
        file = source / name
        if not file.is_file():
            raise ValueError(f"Missing engine source: {name}")
        if verify_source and hashlib.sha256(file.read_bytes()).hexdigest() != data["source_sha256"].get(name):
            raise ValueError(f"Engine source changed: {name}; rerun rippletide setup")
    for name in ("config.json", "tokenizer.json", "model.safetensors"):
        if not (weights / name).is_file():
            raise ValueError(f"Missing model artifact: {name}")
    return data


def setup_artifacts(data_dir: Path) -> dict:
    if not supported_platform():
        raise RuntimeError("This pilot requires Apple Silicon macOS; no alternative backend is selected")
    from huggingface_hub import snapshot_download

    data_dir.mkdir(parents=True, exist_ok=True)
    cache = str(data_dir / "hub")
    source = Path(snapshot_download(ENGINE_ID, revision=ENGINE_REVISION, cache_dir=cache, allow_patterns=list(SOURCE_FILES)))
    weights = Path(snapshot_download(WEIGHTS_ID, revision=WEIGHTS_REVISION, cache_dir=cache))
    digest = hashlib.sha256()
    with (weights / "model.safetensors").open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != WEIGHTS_SHA256:
        raise RuntimeError("Pinned model.safetensors checksum mismatch")
    data = {
        **model_identity(), "source_path": str(source), "weights_path": str(weights),
        "weights_sha256": WEIGHTS_SHA256,
        "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
    }
    manifest = data_dir / "artifacts.json"
    temporary = data_dir / "artifacts.json.tmp"
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(manifest)
    return data
