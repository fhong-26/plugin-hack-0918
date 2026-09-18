"""Process-selected immutable local model options; no model-generated selection."""

import os
from dataclasses import dataclass

DEFAULT_MODEL = "qwen25-rlcd"


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    weights_id: str
    revision: str
    weights_sha256: str
    adapter: str
    prompt_version: str
    quantization: str = "4-bit affine, group_size=64"


MODELS = {
    DEFAULT_MODEL: ModelSpec(
        DEFAULT_MODEL, "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
        "8b403126fc14f14cfc99bb4cfa72ecbc129ea677",
        "0979f33d1bc58afcf696d13f57977644e7b11a6f0eec3e631d8e9463d18c0717",
        "rlcd", "v1-semantic-labels",
    ),
    "qwen3-0.6b": ModelSpec(
        "qwen3-0.6b", "mlx-community/Qwen3-0.6B-4bit",
        "73e3e38d981303bc594367cd910ea6eb48349da8",
        "392e8d466d56100ada00eb82031fb854297fc9e389b7d303eba3af114e87bce2",
        "direct-logit", "v2-tool-choice-labels",
    ),
    "minicpm5-2b": ModelSpec(
        "minicpm5-2b", "openbmb/MiniCPM5-2B-MLX",
        "8a9ad7539ac86281d0ac2b017ba04a5de53fe9a3",
        "c207798696a4a454e7ac211b25227625466c693335941cee8904fb922f295cc1",
        "direct-logit", "v2-tool-choice-labels",
    ),
    "qwen3.5-4b": ModelSpec(
        "qwen3.5-4b", "mlx-community/Qwen3.5-4B-4bit",
        "0e7ffd5c629ef7719d4cbc04069232580bfa9d9c",
        "5fb9acd0246866381cf8c5c354c6db1019f6498eec4ccb4f5edcc71ffeacb2db",
        "direct-logit", "v2-tool-choice-labels",
    ),
}


def model_spec(alias: str | None = None) -> ModelSpec:
    selected = alias if alias is not None else os.environ.get("RIPPLETIDE_MODEL", DEFAULT_MODEL)
    try:
        return MODELS[selected]
    except KeyError:
        raise ValueError(f"Unknown router model {selected!r}; choose one of: {', '.join(MODELS)}") from None
