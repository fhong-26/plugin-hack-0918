"""Resumeable, evidence-preserving, paired routing experiments."""
from __future__ import annotations

import copy
import gc
import json
from pathlib import Path
import time

from rippletide.catalog import model_spec
from rippletide.identity import model_identity
from rippletide.personalization import (atomic_json, read_json, digest, relevant_memory,
    train_residual, adjusted_scores, softmax, init_profile, activate)
from .dataset import read_rows, training_history, PROFILES, preferences
from .evaluation import grade, summary, paired_delta, validation_gate


def make_engine(data_dir: Path, alias: str):
    spec = model_spec(alias)
    if spec.adapter == "torch-direct-logit":
        from rippletide.torch_engine import TorchEngine
        return TorchEngine(data_dir, alias, personalize=False)
    if spec.adapter == "direct-logit":
        from rippletide.direct_logit import DirectLogitEngine
        import os
        if os.environ.get("RIPPLETIDE_PROFILE"):
            raise ValueError("Unset RIPPLETIDE_PROFILE for an isolated benchmark")
        return DirectLogitEngine(data_dir, alias, personalize=False)
    raise ValueError("Personalization lab requires a direct-logit backend. RLCD remains a separate existing-product baseline.")


def with_memory(row: dict, history: list[dict]) -> dict:
    packet = copy.deepcopy(row["packet"])
    packet["preference_memory"] = relevant_memory(packet,
        [r for r in history if r["decision_id"] != row["id"]], row["preferences"], limit=1)
    return packet


def residual_result(packet: dict, result: dict, policy: dict) -> dict:
    if "candidate_logits" not in result:
        return result  # A context failure cannot be repaired by inventing scores.
    scores = softmax(adjusted_scores(packet, result["candidate_logits"], policy))
    index = max(range(len(scores)), key=scores.__getitem__)
    route = result["candidate_ids"][index]
    return {**result, "status": "defer" if route == "defer" else "selected",
            "route_id": None if route == "defer" else route,
            "reason_code": "MODEL_DEFER" if route == "defer" else "MODEL_SELECTION",
            "candidate_probabilities": scores, "score": scores[index],
            "personalization": {"mode": "residual", "policy_digest": digest(policy)}}


def progress(run: Path, value: dict) -> None:
    value = {**value, "timestamp_unix": time.time()}
    with (run / "progress.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value) + "\n")
    if value.get("step", 0) % 10 == 0 or value.get("phase") != "lora_train":
        print(json.dumps(value), flush=True)


def run(dataset: Path, output: Path, data_dir: Path, *, model: str = "qwen3-0.6b-torch",
        epochs: int = 1, rank: int = 4, layers: int = 2, train_limit: int | None = None,
        users: list[str] | None = None, include_lora: bool = True) -> dict:
    users = users or list(PROFILES)
    if set(users) - set(PROFILES):
        raise ValueError("Unknown benchmark user")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "model_identity": model_identity(model), "dataset": read_json(dataset / "manifest.json"),
                "epochs": epochs, "rank": rank, "layers": layers, "train_limit_per_user": train_limit,
                "users": users, "include_lora": include_lora,
                "arms": ["current", "memory", "residual"] + (["lora"] if include_lora else []),
                "level": "routing-component; not end-to-end Codex", "seed": 31}
    if (output / "manifest.json").exists() and read_json(output / "manifest.json") != manifest:
        raise ValueError("Run identity differs. Preserve this run and select a new output directory")
    atomic_json(output / "manifest.json", manifest)
    groups = {split: [r for r in read_rows(dataset, split) if r["user_id"] in users]
              for split in ("train", "validation", "test")}
    train = groups["train"]
    if train_limit:
        # Deterministic random subset per user, fixed before test.
        chosen = []
        for user in users:
            subset = [r for r in train if r["user_id"] == user and r["kind"] != "rule"]
            import random
            random.Random(31).shuffle(subset)
            chosen.extend(subset[:train_limit])
        train = chosen
    else:
        train = [r for r in train if r["kind"] != "rule"]
    history = {u: training_history(train, u) for u in users}
    engine = make_engine(data_dir, model)
    progress(output, {"phase": "model_loaded", "model": model})
    cache = output / "predictions"
    cache.mkdir(exist_ok=True)
    features = output / "frozen-features"
    features.mkdir(exist_ok=True)

    def infer(row, arm, packet=None):
        packet = packet or row["packet"]
        path = cache / f"{arm}-{row['id']}.json"
        input_digest = digest(packet)
        feature_path = features / f"{row['id']}.safetensors"
        capture = (row["split"] == "train" and arm == "memory" and engine.spec.adapter == "torch-direct-logit")
        if path.exists() and (not capture or feature_path.exists()):
            record = read_json(path)
            if record["input_digest"] != input_digest:
                raise ValueError("Cached prediction context differs")
            return record["result"]
        if row["kind"] == "rule":
            # Exercise the actual rule-first router, with an inference tripwire.
            from rippletide.router import Router
            class RulesOnly:
                model = engine.spec.alias
                def predict(self, *args, **kwargs):
                    raise AssertionError("This rule case must not reach the model")
                def close(self):
                    pass
            root = output / "rule-workspace"
            atomic_json(root / ".rippletide/config.json", {"capabilities": row["registry"], "variant": "D"})
            router = Router(worker=RulesOnly(), model=model, data_dir=data_dir)
            result = router.route(project_root=str(root.resolve()), **{k: row["packet"][k] for k in ("goal", "operation", "facts", "recent_observations")})
        else:
            if capture:
                engine.capture_layer = engine.model.config.num_hidden_layers - layers
            result = engine.predict(packet)
            if capture:
                from safetensors.torch import save_file
                if engine.captured_hidden is not None:
                    save_file({"hidden": engine.captured_hidden}, str(feature_path))
                engine.captured_hidden = None
                engine.capture_layer = None
        atomic_json(path, {"id": row["id"], "arm": arm, "input_digest": input_digest, "result": result})
        return result

    results = {arm: {split: [] for split in ("validation", "test")} for arm in manifest["arms"]}
    memory_train = {}
    for user in users:
        rows = [r for r in train if r["user_id"] == user]
        prepared = []
        for i, row in enumerate(rows):
            packet = with_memory(row, history[user])
            result = infer(row, "memory", packet)
            if "candidate_logits" not in result:
                raise RuntimeError(f"Cannot train from unavailable model scores: {row['id']}: {result}")
            prepared.append({**row, "packet": packet, "candidate_logits": result["candidate_logits"]})
            if (features / f"{row['id']}.safetensors").exists():
                prepared[-1]["frozen_features"] = str((features / f"{row['id']}.safetensors").resolve())
            progress(output, {"phase": "training_features", "user": user, "done": i + 1, "total": len(rows)})
        memory_train[user] = prepared

    # Validation is available for selection. Final-test predictions are taken
    # only after all residual hyperparameters have been selected.
    memory_results = {}
    for row in groups["validation"]:
        for arm in ("current", "memory"):
            packet = with_memory(row, history[row["user_id"]]) if arm == "memory" else row["packet"]
            result = infer(row, arm, packet)
            results[arm]["validation"].append(grade(row, result))
            if arm == "memory":
                memory_results[row["id"]] = result
        progress(output, {"phase": "validation", "done": len(results["current"]["validation"]), "total": len(groups["validation"])})
    policies = {}
    for user in users:
        candidates = []
        for learning_rate in (0.1, 0.3):
            policy = train_residual(memory_train[user], rate=learning_rate)
            grades = [grade(row, residual_result(with_memory(row, history[user]), memory_results[row["id"]], policy))
                      for row in groups["validation"] if row["user_id"] == user]
            stats = summary(grades)
            candidates.append((stats["objective"]["matched"], stats["preference"]["matched"], -learning_rate, policy, grades))
        best = max(candidates, key=lambda c: c[:3])
        policies[user] = best[3]
        results["residual"]["validation"].extend(best[4])
        atomic_json(output / "policies" / f"{user}.json", policies[user])
        gate = validation_gate([r for r in results["memory"]["validation"] if r["user_id"] == user], best[4])
        atomic_json(output / "policies" / f"{user}-validation.json", gate)
    for row in groups["test"]:
        packet = with_memory(row, history[row["user_id"]])
        current, memory = infer(row, "current"), infer(row, "memory", packet)
        residual = residual_result(packet, memory, policies[row["user_id"]]) if row["kind"] != "rule" else memory
        for arm, result in (("current", current), ("memory", memory), ("residual", residual)):
            results[arm]["test"].append(grade(row, result))
        progress(output, {"phase": "test_frozen", "done": len(results["current"]["test"]), "total": len(groups["test"])})
    atomic_json(output / "grades.json", results)

    if include_lora:
        from rippletide.lora_training import train_torch, train_mlx
        for user in users:
            adapter = output / "adapters" / user
            if not (adapter / "rippletide_adapter.json").exists():
                trainer = train_torch if engine.spec.adapter == "torch-direct-logit" else train_mlx
                trainer(engine, memory_train[user], adapter, epochs=epochs, rank=rank, layers=layers,
                        progress=lambda item: progress(output, {**item, "user": user}))
            elif engine.spec.adapter == "torch-direct-logit":
                from peft import PeftModel
                engine.model = PeftModel.from_pretrained(engine.model, str(adapter), is_trainable=False)
            else:
                from mlx_lm.tuner.utils import load_adapters
                engine.model = load_adapters(engine.model, str(adapter))
            for split in ("validation", "test"):
                rows = [r for r in groups[split] if r["user_id"] == user]
                for i, row in enumerate(rows):
                    result = infer(row, "lora", with_memory(row, history[user]))
                    results["lora"][split].append(grade(row, result))
                    progress(output, {"phase": "lora_" + split, "user": user, "done": i + 1, "total": len(rows)})
            gate = validation_gate([r for r in results["memory"]["validation"] if r["user_id"] == user],
                                   [r for r in results["lora"]["validation"] if r["user_id"] == user])
            atomic_json(adapter / "validation.json", gate)
            # Save measured candidate performance even when promotion is rejected.
            atomic_json(output / "grades.json", results)
            if engine.spec.adapter == "torch-direct-logit":
                engine.model = engine.model.unload()
                engine.model.eval()
                gc.collect()
            else:
                del engine
                gc.collect()
                engine = make_engine(data_dir, model)
    final = {"manifest": manifest, "results": {arm: {split: summary(rows) for split, rows in splits.items()}
                                             for arm, splits in results.items()},
             "test_comparisons": {arm: paired_delta(results["current"]["test"], results[arm]["test"])
                                  for arm in results if arm != "current"},
             "training_vs_memory": {arm: paired_delta(results["memory"]["test"], results[arm]["test"])
                                    for arm in results if arm in {"residual", "lora"}},
             "end_to_end": {"status": "not_run", "reason": "Use the separate task comparison harness"}}
    atomic_json(output / "results.json", final)
    return final
