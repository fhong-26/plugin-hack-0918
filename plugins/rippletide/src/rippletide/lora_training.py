"""Actual LoRA training on routing-label loss, with pinned base provenance.

Training is an explicit/background job, never part of the routing deadline.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import time

from rippletide.direct_logit import LABELS, DEFER_LABEL, prepare_input, messages_for
from rippletide.identity import INPUT_TOKEN_LIMIT, model_identity
from rippletide.personalization import atomic_json, digest


def adapter_manifest(path: Path, model: str, backend: str, training: dict) -> dict:
    files = {str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
             for file in path.rglob("*") if file.is_file() and file.name != "rippletide_adapter.json"}
    if not any(name.endswith(".safetensors") for name in files):
        raise ValueError("Training did not produce adapter weights")
    manifest = {"version": 1, "base_identity": model_identity(model), "backend": backend,
                "files": files, "training": training, "training_data_uploaded": False}
    atomic_json(path / "rippletide_adapter.json", manifest)
    return manifest


def train_torch(engine, rows: list[dict], output: Path, *, epochs: int = 2, rank: int = 4,
                layers: int = 2, learning_rate: float = 0.0002, seed: int = 31,
                progress=None) -> dict:
    """Train q/v projection adapters in the final layers using candidate CE.

The objective matches inference: one token among eligible candidates + defer.
Base weights remain frozen; adapters are saved separately, never merged.
The caller must evaluate on validation before promoting this candidate.
"""
    from peft import LoraConfig, get_peft_model
    import torch
    if not rows or epochs < 1 or rank < 1:
        raise ValueError("Training requires examples and positive hyperparameters")
    if any(row.get("split", "train") != "train" for row in rows):
        raise ValueError("LoRA training accepts only the training split")
    output.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(seed)
    rng = random.Random(seed)
    count = engine.model.config.num_hidden_layers
    if not 1 <= layers <= count:
        raise ValueError("Invalid number of trainable layers")
    config = LoraConfig(r=rank, lora_alpha=rank * 2, lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"], layers_to_transform=list(range(count - layers, count)),
        bias="none", task_type="CAUSAL_LM")
    engine.model = get_peft_model(engine.model, config)
    engine.model.train()
    trainable = [p for p in engine.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=learning_rate, weight_decay=0.01)
    prepared = []
    for row in rows:
        packet = row["packet"]
        tokens, _ = prepare_input(engine.tokenizer, packet)
        if len(tokens) > INPUT_TOKEN_LIMIT:
            raise ValueError("Training example exceeds the inference context budget")
        routes = [c["id"] for c in packet["candidates"]] + ["defer"]
        labels = list(LABELS[:len(routes) - 1]) + [DEFER_LABEL]
        prepared.append((tokens, [engine.label_ids[x] for x in labels], routes.index(row["preferred_route"]), row.get("frozen_features")))
    started = time.perf_counter()
    losses = []
    steps = 0
    try:
        for epoch in range(epochs):
            indices = list(range(len(prepared)))
            rng.shuffle(indices)
            for index in indices:
                tokens, allowed, target, frozen_features = prepared[index]
                optimizer.zero_grad(set_to_none=True)
                if frozen_features:
                    from safetensors.torch import load_file
                    captured = load_file(frozen_features)["hidden"]
                    base = engine.model.get_base_model()
                    full_layers = base.model.layers
                    try:
                        base.model.layers = torch.nn.ModuleList(list(full_layers)[-layers:])
                        logits = engine.model(inputs_embeds=captured, use_cache=False,
                                              logits_to_keep=1).logits[0, -1, allowed].float()
                    finally:
                        base.model.layers = full_layers
                else:
                    logits = engine.logits(tokens)[allowed].float()
                loss = torch.nn.functional.cross_entropy(logits[None], torch.tensor([target]))
                if not torch.isfinite(loss):
                    raise RuntimeError("Nonfinite LoRA loss; candidate cannot be activated")
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True)
                optimizer.step()
                steps += 1
                losses.append(float(loss.detach()))
                if progress:
                    progress({"phase": "lora_train", "epoch": epoch + 1, "step": steps,
                              "total_steps": epochs * len(prepared), "loss": losses[-1],
                              "gradient_norm": float(norm), "elapsed_seconds": time.perf_counter() - started})
        engine.model.save_pretrained(output, safe_serialization=True)
        training = {"method": "LoRA", "objective": "eligible-candidate-cross-entropy",
            "rank": rank, "layers": layers, "target_modules": ["q_proj", "v_proj"],
            "learning_rate": learning_rate, "epochs": epochs, "seed": seed,
            "examples": len(rows), "steps": steps, "training_digest": digest(rows),
            "trainable_parameters": sum(p.numel() for p in trainable),
            "loss_first": losses[0], "loss_last": losses[-1], "loss_mean": sum(losses) / len(losses),
            "seconds": time.perf_counter() - started, "base_weights_frozen": True,
            "cached_frozen_prefix": all(bool(row.get("frozen_features")) for row in rows),
            "validated": False}
        atomic_json(output / "training.json", training)
        return adapter_manifest(output, engine.spec.alias, "torch", training)
    finally:
        engine.model.eval()
        optimizer.zero_grad(set_to_none=True)


def train_mlx(engine, rows: list[dict], output: Path, *, epochs: int = 2, rank: int = 4,
              layers: int = 2, learning_rate: float = 0.0002, seed: int = 31,
              progress=None) -> dict:
    """MLX LoRA using the same constrained classification loss as inference."""
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from mlx_lm.tuner.utils import linear_to_lora_layers
    from mlx_lm.models.cache import make_prompt_cache
    if engine.spec.adapter != "direct-logit":
        raise ValueError("The MLX LoRA trainer requires a direct-logit model, not the upstream RLCD engine")
    if not rows or any(row.get("split", "train") != "train" for row in rows):
        raise ValueError("LoRA training requires training-split examples")
    if not 1 <= layers <= len(engine.model.layers) or epochs < 1 or rank < 1:
        raise ValueError("Invalid LoRA hyperparameters")
    output.mkdir(parents=True, exist_ok=False)
    mx.random.seed(seed)
    rng = random.Random(seed)
    engine.model.freeze()
    parameters = {"rank": rank, "scale": rank * 2, "dropout": 0.05, "keys": ["self_attn.q_proj", "self_attn.v_proj"]}
    linear_to_lora_layers(engine.model, layers, parameters)
    optimizer = optim.AdamW(learning_rate=learning_rate)

    def loss_fn(model, tokens, allowed, target):
        logits = model(tokens, cache=make_prompt_cache(model))[:, -1, :][:, allowed]
        return nn.losses.cross_entropy(logits.astype(mx.float32), target).mean()

    loss_and_grad = nn.value_and_grad(engine.model, loss_fn)
    started, steps, losses = time.perf_counter(), 0, []
    prepared = []
    for row in rows:
        packet = row["packet"]
        tokens, _ = prepare_input(engine.tokenizer, packet)
        if len(tokens) > INPUT_TOKEN_LIMIT:
            raise ValueError("Training input exceeds inference token budget")
        routes = [c["id"] for c in packet["candidates"]] + ["defer"]
        labels = list(LABELS[:len(routes) - 1]) + [DEFER_LABEL]
        prepared.append((mx.array([tokens]), mx.array([engine.label_ids[label] for label in labels]),
                         mx.array([routes.index(row["preferred_route"])])))
    engine.model.train()
    try:
        for epoch in range(epochs):
            indices = list(range(len(prepared)))
            rng.shuffle(indices)
            for index in indices:
                loss, gradients = loss_and_grad(engine.model, *prepared[index])
                optimizer.update(engine.model, gradients)
                mx.eval(engine.model.parameters(), optimizer.state, loss)
                if not bool(mx.isfinite(loss).item()):
                    raise RuntimeError("Nonfinite training loss")
                steps += 1
                losses.append(loss.item())
                if progress:
                    progress({"phase": "lora_train", "step": steps, "total_steps": epochs * len(prepared),
                              "loss": losses[-1], "elapsed_seconds": time.perf_counter() - started})
        mx.save_safetensors(str(output / "adapters.safetensors"), dict(tree_flatten(engine.model.trainable_parameters())))
        atomic_json(output / "adapter_config.json", {"fine_tune_type": "lora", "num_layers": layers,
                    "lora_parameters": parameters})
        training = {"method": "LoRA", "objective": "eligible-candidate-cross-entropy", "rank": rank,
                    "layers": layers, "learning_rate": learning_rate, "epochs": epochs, "seed": seed,
                    "examples": len(rows), "steps": steps, "training_digest": digest(rows),
                    "loss_first": losses[0], "loss_last": losses[-1], "base_weights_frozen": True,
                    "seconds": time.perf_counter() - started, "validated": False}
        atomic_json(output / "training.json", training)
        return adapter_manifest(output, engine.spec.alias, "mlx", training)
    finally:
        engine.model.eval()
