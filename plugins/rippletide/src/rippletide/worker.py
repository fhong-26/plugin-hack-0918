"""Isolated persistent MLX worker. stdout is exclusively newline-delimited JSON."""

import argparse
import contextlib
import json
import string
import sys
import time
from pathlib import Path

from rippletide.artifacts import read_artifacts, supported_platform
from rippletide.identity import INPUT_TOKEN_LIMIT

SEMANTIC_LABELS = {
    "native.filename_search": "filename",
    "native.lexical_search": "grep",
    "mcp.semantic_search": "semantic",
    "mcp.docs_search": "docs",
    "mcp.tracker_search": "issues",
    "agent.reviewer": "review",
    "agent.test_specialist": "tests",
}


def build_context(request: dict, candidates: list[dict], labels: list[str], observations: list[dict]) -> str:
    context = request["goal"]
    if request.get("facts"):
        context += "\nTask facts (data): " + json.dumps(request["facts"], ensure_ascii=False, sort_keys=True)
    if observations:
        context += "\nRecent observations (data): " + json.dumps(observations, ensure_ascii=False, sort_keys=True)
    return context


def full_upstream_prompt(context: str, schema) -> str:
    # Must match the pinned engine's base_prompt exactly to count all model input.
    return (
        f"<|im_start|>system\nClassify JSON attributes:\n{schema.to_parallel_schema_str()}<|im_end|>\n"
        f"<|im_start|>user\n{context}<|im_end|>\n<|im_start|>assistant\n{{\n"
    )


class Engine:
    def __init__(self, data_dir: Path):
        if not supported_platform():
            raise RuntimeError("Apple Silicon MLX is required")
        artifacts = read_artifacts(data_dir, verify_source=True)
        # Import MLX before upstream core.__init__: never allow its Torch fallback.
        import mlx.core  # noqa: F401
        import mlx_lm  # noqa: F401
        sys.path.insert(0, artifacts["source_path"])
        from core import engine_mlx
        from core.schema import StructuredSchema
        engine_mlx.MODEL_ID = artifacts["weights_path"]
        self.engine = engine_mlx
        self.schema_type = StructuredSchema
        self.model, self.tokenizer = engine_mlx.get_engine()
        all_labels = list(string.ascii_uppercase) + list(SEMANTIC_LABELS.values()) + ["defer"]
        tokens = [self.tokenizer.encode(label, add_special_tokens=False) for label in all_labels]
        if any(len(ids) != 1 for ids in tokens) or len({ids[0] for ids in tokens}) != len(all_labels):
            raise RuntimeError("Pinned tokenizer does not provide distinct one-token routing labels")

    def predict(self, packet: dict) -> dict:
        candidates = packet["candidates"]
        if not 1 <= len(candidates) <= 25:
            return {"status": "defer", "reason_code": "TOO_MANY_CANDIDATES"}
        labels = [SEMANTIC_LABELS.get(cap["id"], string.ascii_uppercase[index]) for index, cap in enumerate(candidates)]
        choices = labels + ["defer"]
        catalog = "; ".join(f"{label} for {cap['description'].replace(chr(10), ' ')}" for label, cap in zip(labels, candidates))
        schema = self.schema_type({"route": {
            "type": "enum", "choices": choices,
            "description": f"Select {catalog}; defer only for an unrelated or unclear task.",
        }})
        metadata = schema.compile_parallel_metadata(self.tokenizer)
        if any(metadata["has_collisions"]):
            return {"status": "defer", "reason_code": "LABEL_TOKEN_COLLISION"}
        observations = list(packet.get("recent_observations", []))
        while True:
            context = build_context(packet, candidates, labels, observations)
            # Prefix plus actual suffix: both contribute to the complete model input.
            token_count = len(self.tokenizer.encode(full_upstream_prompt(context, schema))) + max(metadata["suffix_lengths"])
            if token_count <= INPUT_TOKEN_LIMIT:
                break
            if observations:
                observations.pop(0)
            else:
                return {"status": "defer", "reason_code": "CONTEXT_TOO_LARGE", "input_tokens": token_count, "observations_used": 0}
        result = self.engine.run_parallel_generation(context, schema, temperature=1.0)
        selected = result["parsed_json"]["route"]["value"]
        common = {
            "prompt_version": "v1-semantic-labels",
            "score": result["parsed_json"]["route"]["prob"],
            "score_kind": "uncalibrated_candidate_softmax",
            "input_tokens": token_count, "observations_used": len(observations),
            "inference_ms": result["elapsed_ms"],
        }
        if selected == "defer":
            return {"status": "defer", "reason_code": "MODEL_DEFER", **common}
        if selected not in labels:
            return {"status": "defer", "reason_code": "INVALID_MODEL_OUTPUT", **common}
        return {"status": "selected", "route_id": candidates[labels.index(selected)]["id"], "reason_code": "MODEL_SELECTION", **common}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    protocol = sys.stdout

    def send(message):
        try:
            protocol.write(json.dumps(message, ensure_ascii=False) + "\n")
            protocol.flush()
        except BrokenPipeError:
            # The MCP client may disconnect during warmup. This is a normal
            # shutdown, not a startup error to write to the same closed pipe.
            try:
                protocol.close()
            except BrokenPipeError:
                pass
            raise SystemExit(0)

    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            engine = Engine(args.data_dir)
        send({"type": "ready", "startup_ms": (time.perf_counter() - started) * 1000})
    except Exception as exc:
        send({"type": "startup_error", "error": str(exc)})
        return
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = engine.predict(packet)
            send({"type": "result", "result": result})
        except Exception as exc:
            send({"type": "result", "result": {"status": "defer", "reason_code": "MODEL_ERROR", "error": str(exc)}})


if __name__ == "__main__":
    main()
