"""Explicit portable CPU reference backend; never an implicit MLX substitute."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

from rippletide.artifacts import read_artifacts
from rippletide.catalog import model_spec
from rippletide.direct_logit import LABELS, DEFER_LABEL, prepare_input, validated_label_ids
from rippletide.identity import INPUT_TOKEN_LIMIT, model_identity
from rippletide.personalization import Personalizer, adjusted_scores, softmax


class TorchEngine:
    def __init__(self, data_dir: Path, model: str = "qwen3-0.6b-torch", *, personalize: bool = True):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.spec = model_spec(model)
        if self.spec.adapter != "torch-direct-logit":
            raise ValueError("Use an explicitly registered Torch model")
        artifacts = read_artifacts(data_dir, verify_source=True, model=model)
        self.weights_path = artifacts["weights_path"]
        self.torch = torch
        torch.set_num_threads(int(os.environ.get("RIPPLETIDE_CPU_THREADS", "4")))
        self.model = AutoModelForCausalLM.from_pretrained(self.weights_path,
            local_files_only=True, trust_remote_code=False, torch_dtype=torch.float16,
            attn_implementation="sdpa", low_cpu_mem_usage=True)
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(self.weights_path, local_files_only=True,
                                                       trust_remote_code=False)
        self.label_ids = validated_label_ids(self.tokenizer)
        self.capture_layer = None
        self.captured_hidden = None
        self.personalizer = Personalizer() if personalize else None
        if self.personalizer:
            self.personalizer.validate_base(model_identity(model), "torch")
            if self.personalizer.adapter_path:
                from peft import PeftModel
                self.model = PeftModel.from_pretrained(self.model, str(self.personalizer.adapter_path),
                                                       is_trainable=False)
                self.model.eval()

    def logits(self, tokens: list[int]):
        return self.model(input_ids=self.torch.tensor([tokens], dtype=self.torch.long),
                          use_cache=False, logits_to_keep=1).logits[0, -1, :]

    def predict(self, packet: dict) -> dict:
        if self.personalizer:
            packet = self.personalizer.packet(packet)
        candidates = packet["candidates"]
        if not 1 <= len(candidates) <= 25:
            return {"status": "defer", "reason_code": "TOO_MANY_CANDIDATES"}
        tokens, observations = prepare_input(self.tokenizer, packet)
        common = {"prompt_version": self.spec.prompt_version, "input_tokens": len(tokens),
            "observations_used": len(observations), "output_tokens": 0, "readout_tokens": 1,
            "prompt_sha256": hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode()).hexdigest()}
        if len(tokens) > INPUT_TOKEN_LIMIT:
            return {"status": "defer", "reason_code": "CONTEXT_TOO_LARGE", **common}
        labels = list(LABELS[:len(candidates)]) + [DEFER_LABEL]
        started = time.perf_counter()
        hook = None
        self.captured_hidden = None
        if self.capture_layer is not None:
            def capture(module, args, kwargs):
                value = args[0] if args else kwargs["hidden_states"]
                self.captured_hidden = value.detach().clone().contiguous()
            hook = self.model.model.layers[self.capture_layer].register_forward_pre_hook(capture, with_kwargs=True)
        try:
            with self.torch.no_grad():
                raw = self.logits(tokens)[[self.label_ids[x] for x in labels]].float().tolist()
        finally:
            if hook:
                hook.remove()
        policy = self.personalizer.policy if self.personalizer else None
        scores = softmax(adjusted_scores(packet, raw, policy))
        index = max(range(len(scores)), key=scores.__getitem__)
        common.update(score=scores[index], score_kind="uncalibrated_candidate_softmax",
            candidate_ids=[c["id"] for c in candidates] + ["defer"], candidate_logits=raw,
            candidate_probabilities=scores, label=labels[index], label_token_id=self.label_ids[labels[index]],
            inference_ms=round((time.perf_counter() - started) * 1000, 3),
            personalization=self.personalizer.identity() if self.personalizer else {"mode": "off"})
        if labels[index] == DEFER_LABEL:
            return {"status": "defer", "reason_code": "MODEL_DEFER", **common}
        return {"status": "selected", "route_id": candidates[index]["id"], "reason_code": "MODEL_SELECTION", **common}
