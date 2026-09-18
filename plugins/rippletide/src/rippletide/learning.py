"""First-use setup, explicit corrections, background learning, and rollback."""
from __future__ import annotations

import argparse
import asyncio
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from rippletide.personalization import (MODES, Personalizer, init_profile, configure_profile,
    record_feedback, atomic_json, read_json, digest, default_profile_path, relevant_memory,
    train_residual, adjusted_scores, softmax, activate, rollback, exclusive)


def status(path: Path | None = None) -> dict:
    path = path or default_profile_path()
    if not (path / "profile.json").exists():
        return {"configured": False, "state": "setup_available", "profile_path": str(path),
                "message": "Optional first-use setup: supply preferences and choose whether explicit corrections may train a local policy."}
    personalizer = Personalizer(path)
    return {"configured": True, "profile": personalizer.profile, "identity": personalizer.identity(),
            "examples": len(personalizer.records), "restart_worker_after_changes": True,
            "last_job": read_json(path / "last-job.json") if (path / "last-job.json").exists() else None}


def _grade(rows, predictions):
    matches = sum((p.get("route_id") if p.get("status") == "selected" else "defer") == r["preferred_route"]
                  and p.get("reason_code") in {"MODEL_SELECTION", "MODEL_DEFER"}
                  for r, p in zip(rows, predictions))
    errors = sum(p.get("reason_code") not in {"MODEL_SELECTION", "MODEL_DEFER"} for p in predictions)
    return {"matched": matches, "total": len(rows), "errors": errors}


def _residual_predictions(packets, results, policy):
    predictions = []
    for value, result in zip(packets, results):
        if "candidate_logits" not in result:
            predictions.append(result)
            continue
        scores = softmax(adjusted_scores(value, result["candidate_logits"], policy))
        route = result["candidate_ids"][max(range(len(scores)), key=scores.__getitem__)]
        predictions.append({"status": "defer" if route == "defer" else "selected",
            "route_id": None if route == "defer" else route,
            "reason_code": "MODEL_DEFER" if route == "defer" else "MODEL_SELECTION"})
    return predictions


def training_input_digest(profile, records, model, method):
    return digest({"feedback": records, "preferences": profile["preferences"],
                   "model": model, "method": method})


def train_profile(path: Path, model: str, *, method: str = "residual", epochs: int = 1) -> dict:
    """Candidate training plus a conservative correction-validation gate.

These are preference labels, not independent task-outcome evidence. Production
promotion requires at least six held-out corrections and no new inference
errors. Real task acceptance is assessed separately by the lab task runner.
"""
    from rippletide.catalog import model_spec
    from rippletide.identity import data_directory, model_identity
    spec = model_spec(model)
    if method not in {"residual", "lora"} or spec.adapter == "rlcd":
        raise ValueError("Choose residual or LoRA and an explicitly configured direct-logit model")
    with exclusive(path / ".training.lock"):
        profile = read_json(path / "profile.json")
        records = read_json(path / "feedback.json")
        if not profile["learning_enabled"] or len(records) < profile["minimum_examples"]:
            raise ValueError("Learning is disabled or there are too few explicit corrections")
        if any(r["user_id"] != profile["user_id"] or r["source"] != "explicit_user" for r in records):
            raise ValueError("Training history contains another user's records or untrusted labels")
        # Whole families have one fixed split. No final test set is used here.
        train, valid = [], []
        for record in records:
            (valid if int(digest(record["family_id"])[:8], 16) % 5 == 0 else train).append(record)
        if len(valid) < 6 or len(train) < 10:
            raise ValueError("Need at least 10 training and 6 validation corrections in disjoint families")
        identity = model_identity(model)
        incumbent = Personalizer(path)
        incumbent.validate_base(identity, identity["backend"])
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + digest(records)[:8]
        version = path / "versions" / job_id
        version.mkdir(parents=True, exist_ok=False)
        job = {"job_id": job_id, "status": "running", "feedback_digest": digest(records),
               "input_digest": training_input_digest(profile, records, model, method),
               "method": method, "base_identity": identity, "train": len(train), "validation": len(valid)}
        atomic_json(path / "last-job.json", job)
        try:
            if spec.adapter == "torch-direct-logit":
                from rippletide.torch_engine import TorchEngine
                engine = TorchEngine(data_directory(), model, personalize=False)
            else:
                from rippletide.direct_logit import DirectLogitEngine
                engine = DirectLogitEngine(data_directory(), model, personalize=False)
            def packet(record):
                value = copy.deepcopy(record["packet"])
                value["preference_memory"] = relevant_memory(value,
                    [r for r in train if r["decision_id"] != record["decision_id"]], profile["preferences"], limit=1)
                return value
            prepared = [{**r, "packet": packet(r), "split": "train"} for r in train]
            valid_packets = [packet(r) for r in valid]
            baseline_results = [engine.predict(p) for p in valid_packets]
            baseline = _grade(valid, baseline_results)
            incumbent_grade = baseline
            if incumbent.policy is not None:
                incumbent_grade = _grade(valid, _residual_predictions(valid_packets, baseline_results, incumbent.policy))
            elif incumbent.adapter_path is not None:
                if spec.adapter == "torch-direct-logit":
                    from peft import PeftModel
                    engine.model = PeftModel.from_pretrained(engine.model, str(incumbent.adapter_path), is_trainable=False)
                    incumbent_grade = _grade(valid, [engine.predict(p) for p in valid_packets])
                    engine.model = engine.model.unload()
                    engine.model.eval()
                else:
                    from mlx_lm.tuner.utils import load_adapters
                    engine.model = load_adapters(engine.model, str(incumbent.adapter_path))
                    incumbent_grade = _grade(valid, [engine.predict(p) for p in valid_packets])
                    del engine
                    import gc
                    gc.collect()
                    engine = DirectLogitEngine(data_directory(), model, personalize=False)
            if method == "residual":
                for record in prepared:
                    result = engine.predict(record["packet"])
                    if "candidate_logits" not in result:
                        raise ValueError("A training request could not be scored")
                    record["candidate_logits"] = result["candidate_logits"]
                policy = train_residual(prepared)
                artifact = version / "residual.json"
                atomic_json(artifact, policy)
                candidate_results = _residual_predictions(valid_packets, baseline_results, policy)
            else:
                from rippletide.lora_training import train_torch, train_mlx
                artifact = version / "lora"
                trainer = train_torch if spec.adapter == "torch-direct-logit" else train_mlx
                trainer(engine, prepared, artifact, epochs=epochs)
                candidate_results = [engine.predict(p) for p in valid_packets]
            candidate = _grade(valid, candidate_results)
            validation = {"passed": candidate["matched"] > max(baseline["matched"], incumbent_grade["matched"]) and candidate["errors"] == 0,
                          "baseline": baseline, "incumbent": incumbent_grade, "candidate": candidate,
                          "family_split_digest": digest({"train": [r["decision_id"] for r in train],
                                                         "validation": [r["decision_id"] for r in valid]}),
                          "scope": "held-out explicit preference corrections; task outcome not established"}
            atomic_json(version / "validation.json", validation)
            if validation["passed"]:
                latest = Personalizer(path)
                if latest.profile != incumbent.profile or latest.active != incumbent.active:
                    raise ValueError("Profile or active model changed during training; candidate retained without activation")
                activate(path, mode=method, artifact=artifact, base_identity=identity,
                         backend=identity["backend"], validation=validation)
            job.update(status="activated" if validation["passed"] else "rejected", validation=validation)
            atomic_json(path / "last-job.json", job)
            return job
        except Exception as exc:
            job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            atomic_json(path / "last-job.json", job)
            raise


async def automatic_learning(router) -> None:
    """Run only after prior opt-in and enough new explicit corrections.

Suspend the inference worker during training to avoid holding two base models.
Routing visibly defers during maintenance. No live request waits for training.
"""
    process = None
    try:
        while True:
            await asyncio.sleep(30)
            path = default_profile_path()
            if not (path / "profile.json").exists():
                continue
            profile = read_json(path / "profile.json")
            if not profile["learning_enabled"] or not profile["auto_train"] or profile["mode"] == "off":
                continue
            records = read_json(path / "feedback.json")
            last = read_json(path / "last-job.json") if (path / "last-job.json").exists() else {}
            method = "lora" if profile["mode"] == "lora" else "residual"
            input_digest = training_input_digest(profile, records, router.model, method)
            if len(records) < profile["minimum_examples"] or input_digest == last.get("input_digest"):
                continue
            if router.worker._request_lock.locked():
                continue
            try:
                with exclusive(path / ".training.lock"):
                    pass
            except OSError:
                continue
            router.worker.maintenance = True
            router.worker.close()
            try:
                with (path / "training-output.log").open("ab") as log:
                    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "rippletide.learning", "train",
                        "--profile", str(path), "--model", router.model,
                        "--method", method,
                        stdout=log, stderr=log)
                    await process.wait()
                # Even configuration failures should not spin every 30 seconds.
                last = read_json(path / "last-job.json") if (path / "last-job.json").exists() else {}
                if last.get("input_digest") != input_digest:
                    atomic_json(path / "last-job.json", {"status": "failed", "feedback_digest": digest(records),
                        "input_digest": input_digest,
                        "reason": "Training subprocess could not start an eligible job; inspect training-output.log"})
            finally:
                if process and process.returncode is None:
                    process.terminate()
                    await process.wait()
                process = None
                router.worker.maintenance = False
                if not asyncio.current_task().cancelling():
                    router.worker.start(wait=False)
    finally:
        if process and process.returncode is None:
            process.terminate()
            await process.wait()
        router.worker.maintenance = False


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rippletide learning")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("init", "status", "configure", "feedback", "train", "rollback"):
        command = sub.add_parser(name)
        command.add_argument("--profile", type=Path, default=default_profile_path())
        if name == "init":
            command.add_argument("--user-id", default="local-user")
            command.add_argument("--preference", action="append", default=[])
            command.add_argument("--enable-learning", action="store_true")
            command.add_argument("--auto-train", action="store_true")
            command.add_argument("--mode", choices=MODES, default="memory")
        elif name == "configure":
            command.add_argument("--set", required=True, help="Explicit JSON patch")
        elif name == "feedback":
            command.add_argument("--decision-log", type=Path, required=True)
            command.add_argument("--decision-id", required=True)
            command.add_argument("--prefer", required=True)
            command.add_argument("--family", required=True)
            command.add_argument("--explanation", default="")
        elif name == "train":
            command.add_argument("--model", required=True)
            command.add_argument("--method", choices=["residual", "lora"], default="residual")
            command.add_argument("--epochs", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            result = init_profile(args.profile, user_id=args.user_id, preferences=args.preference,
                learn=args.enable_learning, auto_train=args.auto_train, mode=args.mode)
        elif args.action == "status":
            result = status(args.profile)
        elif args.action == "configure":
            result = configure_profile(args.profile, **json.loads(args.set))
        elif args.action == "rollback":
            result = rollback(args.profile)
        elif args.action == "train":
            result = train_profile(args.profile, args.model, method=args.method, epochs=args.epochs)
        else:
            events = [json.loads(line) for line in args.decision_log.read_text(encoding="utf-8").splitlines() if line]
            matching = [e for e in events if e.get("response", {}).get("decision_id") == args.decision_id]
            if len(matching) != 1:
                raise ValueError("Expected exactly one matching decision in the supplied log")
            result = record_feedback(args.profile, matching[0], args.prefer, family_id=args.family,
                                     explanation=args.explanation)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
