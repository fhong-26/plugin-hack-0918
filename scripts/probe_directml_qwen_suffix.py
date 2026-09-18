"""Probe real Qwen suffix training on DirectML without another full model.

Loads the frozen final two layers and the eligible output-head rows. Uses one
already cached training input, with an arbitrary diagnostic label. This is a
device feasibility probe, never a replacement for the controlled CPU trial.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import time
import traceback
import warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--component-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("directml", "cpu"), default="directml")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--steps", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose a new output path to preserve probe evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {"status": "running", "scope": "Actual final two Qwen layers; cached prefix and reduced output head",
              "not_a_full_model_benchmark": True, "concurrent_cpu_experiment": True,
              "device": args.device, "cpu_threads": args.threads,
              "packages": {p: importlib.metadata.version(p) for p in
                           ("torch", "torch-directml", "transformers", "peft")}}

    def stage(name, **values):
        result.update(stage=name, **values)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"stage": name, **values}), flush=True)

    stage("importing")
    try:
        import torch
        import torch_directml
        from safetensors import safe_open
        from safetensors.torch import load_file
        from transformers import AutoTokenizer, Qwen3Config, Qwen3ForCausalLM
        from peft import LoraConfig, get_peft_model
        torch.set_num_threads(args.threads)
        torch.manual_seed(31)
        identity = json.loads(args.artifacts.read_text(encoding="utf-8"))
        weights = Path(identity["weights_path"])
        feature = sorted((args.component_run / "frozen-features").glob("*.safetensors"))[0]
        prediction = json.loads((args.component_run / "predictions" / f"memory-{feature.stem}.json").read_text(encoding="utf-8"))["result"]
        labels = [chr(65 + i) for i in range(len(prediction["candidate_ids"]) - 1)] + ["Z"]
        tokenizer = AutoTokenizer.from_pretrained(weights, local_files_only=True, trust_remote_code=False)
        ids = [tokenizer.encode(label, add_special_tokens=False)[0] for label in labels]
        del tokenizer
        config_data = json.loads((weights / "config.json").read_text(encoding="utf-8"))
        total_layers = config_data["num_hidden_layers"]
        config_data.update(num_hidden_layers=2, vocab_size=len(ids))
        if config_data.get("layer_types"):
            config_data["layer_types"] = config_data["layer_types"][-2:]
        config = Qwen3Config(**config_data)
        config._attn_implementation = "eager"
        previous_dtype = torch.get_default_dtype()
        try:
            torch.set_default_dtype(torch.float16)
            model = Qwen3ForCausalLM(config)
        finally:
            torch.set_default_dtype(previous_dtype)
        stage("loading_suffix", feature_id=feature.stem, base_revision=identity["weights_revision"],
              attention="eager", base_precision="float16", labels=labels)
        with safe_open(weights / "model.safetensors", framework="pt", device="cpu") as tensors:
            head = tensors.get_slice("model.embed_tokens.weight")
            eligible_head = torch.cat([head[i:i+1] for i in ids]).to(torch.float16)
            for name, parameter in model.named_parameters():
                if name in {"model.embed_tokens.weight", "lm_head.weight"}:
                    value = eligible_head
                else:
                    source = name
                    for index in range(2):
                        prefix = f"model.layers.{index}."
                        if name.startswith(prefix):
                            source = f"model.layers.{total_layers - 2 + index}." + name[len(prefix):]
                            break
                    value = tensors.get_tensor(source).to(torch.float16)
                with torch.no_grad():
                    parameter.copy_(value)
        hidden = load_file(feature)["hidden"]
        model.eval()
        with torch.no_grad():
            reference = model(inputs_embeds=hidden, use_cache=False, logits_to_keep=1).logits[0, -1].float()
        original = torch.tensor(prediction["candidate_logits"])
        reference_error = float((reference - original).abs().max())
        stage("cpu_suffix_verified", cached_full_model_maximum_logit_error=reference_error,
              sequence_length=hidden.shape[1])
        assert reference_error <= 0.125, "Reconstructed suffix differs from cached full model"
        device = torch_directml.device() if args.device == "directml" else torch.device("cpu")
        model.to(device)
        hidden = hidden.to(device)
        started = time.perf_counter()
        with torch.no_grad():
            actual = model(inputs_embeds=hidden, use_cache=False, logits_to_keep=1).logits[0, -1].float().cpu()
        forward_seconds = time.perf_counter() - started
        gpu_error = float((actual - reference).abs().max())
        stage("device_suffix_verified", forward_seconds=forward_seconds,
              device_cpu_maximum_logit_error=gpu_error,
              same_argmax=bool(actual.argmax() == reference.argmax()))
        assert gpu_error <= 0.125, "DirectML suffix differs from CPU reference"
        model = get_peft_model(model, LoraConfig(r=4, lora_alpha=8, lora_dropout=0.05,
            target_modules=["q_proj", "v_proj"], layers_to_transform=[0, 1],
            bias="none", task_type="CAUSAL_LM"))
        model.train()
        trainable = [p for p in model.parameters() if p.requires_grad]
        before = [p.detach().cpu().clone() for p in trainable]
        optimizer = torch.optim.AdamW(trainable, lr=0.0002, weight_decay=0.01, foreach=False)
        steps = []
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            for index in range(args.steps):
                started = time.perf_counter()
                optimizer.zero_grad(set_to_none=True)
                logits = model(inputs_embeds=hidden, use_cache=False, logits_to_keep=1).logits[0, -1].float()
                loss = torch.nn.functional.cross_entropy(logits[None], torch.tensor([0]).to(device))
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0, foreach=False)
                optimizer.step()
                # Wait for the final updated parameter before stopping the GPU
                # timer; asynchronous dispatch alone is not completed work.
                trainable[-1].detach().cpu()
                measured = {"step": index + 1, "loss": float(loss.detach().cpu()),
                            "gradient_norm": float(norm.detach().cpu()),
                            "seconds": time.perf_counter() - started}
                steps.append(measured)
                stage("device_training", steps=steps)
        change = sum(float((p.detach().cpu() - old).abs().sum()) for p, old in zip(trainable, before))
        assert change > 0
        stage("completed", status="passed", trainable_parameters=sum(p.numel() for p in trainable),
              absolute_adapter_change=change, warnings=sorted({str(w.message) for w in observed}))
    except Exception as exc:
        stage("failed", status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
