"""Bounded DirectML compatibility probe, separate from the CPU experiment.

Uses small synthetic tensors and a tiny random Qwen, never benchmark labels or
the trained user adapters. Timings are diagnostic, not full-model speed claims.
"""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
from pathlib import Path
import time
import traceback
import warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError("Preserve earlier probe evidence; choose a fresh output")
    result = {"purpose": "Small operator/LoRA compatibility probe; not full Qwen performance",
              "packages": {name: importlib.metadata.version(name) for name in
                           ("torch", "torch-directml", "transformers", "peft")}, "checks": {}}

    def save():
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    def check(name, function):
        started = time.perf_counter()
        print(json.dumps({"starting": name}), flush=True)
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            try:
                value = {"passed": True, **function()}
            except Exception as exc:
                value = {"passed": False, "error": f"{type(exc).__name__}: {exc}",
                         "traceback": traceback.format_exc()}
            value["warnings"] = sorted({str(w.message) for w in observed})
        value["seconds"] = time.perf_counter() - started
        result["checks"][name] = value
        save()
        print(json.dumps({"check": name, **value}), flush=True)
        return value["passed"]

    save()
    import torch
    import torch_directml
    torch.set_num_threads(1)
    torch.manual_seed(31)
    result["adapters"] = [torch_directml.device_name(i) for i in range(torch_directml.device_count())]
    device = torch_directml.device()
    result["device"] = str(device)
    save()

    def matrix_backward():
        left = torch.randn(128, 128)
        right = torch.randn(128, 128)
        gpu_left = left.to(device).requires_grad_()
        gpu_right = right.to(device).requires_grad_()
        product = gpu_left @ gpu_right
        error = float((product.detach().cpu() - left @ right).abs().max())
        product.square().mean().backward()
        grad = gpu_left.grad.detach().cpu()
        assert torch.isfinite(grad).all() and grad.abs().sum() > 0
        assert torch.allclose(product.detach().cpu(), left @ right, rtol=1e-3, atol=1e-3)
        return {"maximum_absolute_error": error, "gradient_norm": float(grad.norm())}

    if not check("gpu_matrix_forward_backward", matrix_backward):
        return

    from transformers import Qwen3Config, Qwen3ForCausalLM
    from peft import LoraConfig, get_peft_model
    config = Qwen3Config(vocab_size=128, hidden_size=128, intermediate_size=256,
                        num_hidden_layers=2, num_attention_heads=4,
                        num_key_value_heads=2, head_dim=32, max_position_embeddings=128)
    config._attn_implementation = "eager"
    cpu = Qwen3ForCausalLM(config).eval()
    gpu = copy.deepcopy(cpu).to(device).eval()
    tokens = torch.randint(0, 128, (1, 32))

    def qwen_forward():
        with torch.no_grad():
            expected = cpu(input_ids=tokens, use_cache=False).logits
            actual = gpu(input_ids=tokens.to(device), use_cache=False).logits.cpu()
        error = float((expected - actual).abs().max())
        assert torch.allclose(expected, actual, rtol=1e-2, atol=1e-3)
        return {"maximum_absolute_error": error, "sequence_length": 32,
                "model": "random 2-layer, hidden-128 Qwen3", "precision": "float32"}

    if not check("tiny_qwen_forward", qwen_forward):
        return

    def lora_backward():
        model = get_peft_model(gpu, LoraConfig(r=4, lora_alpha=8,
            target_modules=["q_proj", "v_proj"], lora_dropout=0.05,
            bias="none", task_type="CAUSAL_LM"))
        model.train()
        trainable = [p for p in model.parameters() if p.requires_grad]
        before = [p.detach().cpu().clone() for p in trainable]
        optimizer = torch.optim.AdamW(trainable, lr=0.0002, weight_decay=0.01, foreach=False)
        losses = []
        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            logits = model(input_ids=tokens.to(device), use_cache=False).logits[0, -1, :4]
            loss = torch.nn.functional.cross_entropy(logits[None], torch.tensor([1]).to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, 1.0, foreach=False)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        changes = sum(float((p.detach().cpu() - old).abs().sum()) for p, old in zip(trainable, before))
        assert changes > 0
        return {"losses": losses, "total_absolute_adapter_change": changes,
                "trainable_parameters": sum(p.numel() for p in trainable)}

    check("tiny_qwen_lora_backward", lora_backward)


if __name__ == "__main__":
    main()
