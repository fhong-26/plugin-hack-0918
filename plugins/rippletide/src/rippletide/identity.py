"""Immutable upstream identities. The engine repository does not contain weights."""

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from rippletide.catalog import model_spec

ENGINE_ID = "harshatheg/Qwen-2.5-1B-RLCD"
ENGINE_REVISION = "2af86848be75847ccb3553b0941cc51d6ef7e4e9"
WEIGHTS_ID = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
WEIGHTS_REVISION = "8b403126fc14f14cfc99bb4cfa72ecbc129ea677"
WEIGHTS_SHA256 = "0979f33d1bc58afcf696d13f57977644e7b11a6f0eec3e631d8e9463d18c0717"
INPUT_TOKEN_LIMIT = 1024
ROUTE_TIMEOUT_SECONDS = 2.0
SOURCE_FILES = (
    "core/__init__.py", "core/engine.py", "core/engine_mlx.py",
    "core/engine_torch.py", "core/schema.py", "core/prompt_builder.py",
)


def data_directory() -> Path:
    return Path(os.environ.get("RIPPLETIDE_DATA_DIR", "~/.local/share/rippletide")).expanduser().resolve()


def model_identity(alias: str | None = None) -> dict:
    spec = model_spec(alias)
    identity = {
        "model": spec.alias, "adapter": spec.adapter,
        "engine_id": ENGINE_ID if spec.adapter == "rlcd" else "rippletide.direct-logit",
        "engine_revision": ENGINE_REVISION if spec.adapter == "rlcd" else "v1",
        "weights_id": spec.weights_id, "weights_revision": spec.revision,
        "backend": "torch" if spec.adapter == "torch-direct-logit" else "mlx", "temperature": 1.0,
        "quantization": spec.quantization, "prompt_version": spec.prompt_version,
        "decoding": "allowed_token_argmax", "sampling": False,
        "thinking_enabled": False,
    }
    for package in ("mlx-lm", "mlx", "transformers", "torch", "peft"):
        try:
            identity[package.replace("-", "_") + "_version"] = version(package)
        except PackageNotFoundError:
            identity[package.replace("-", "_") + "_version"] = None
    return identity
