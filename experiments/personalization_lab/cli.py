from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="personalization-lab")
    sub = parser.add_subparsers(dest="command", required=True)
    dataset = sub.add_parser("dataset")
    dataset.add_argument("--output", type=Path, required=True)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--data-dir", type=Path, required=True)
    smoke.add_argument("--model", default="qwen3-0.6b-torch")
    smoke.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--data-dir", type=Path, required=True)
    run.add_argument("--model", default="qwen3-0.6b-torch")
    run.add_argument("--epochs", type=int, default=1)
    run.add_argument("--rank", type=int, default=4)
    run.add_argument("--layers", type=int, default=2)
    run.add_argument("--train-limit", type=int)
    run.add_argument("--users", nargs="+")
    run.add_argument("--without-lora", action="store_true")
    reference = sub.add_parser("codex-reference")
    reference.add_argument("--dataset", type=Path, required=True)
    reference.add_argument("--output", type=Path, required=True)
    reference.add_argument("--model", required=True)
    reference.add_argument("--effort", default="high")
    reference.add_argument("--limit", type=int)
    reference.add_argument("--train-limit", type=int, default=12)
    task = sub.add_parser("task")
    task.add_argument("--output", type=Path, required=True)
    task.add_argument("--dataset", type=Path, required=True)
    task.add_argument("--component-run", type=Path, required=True)
    task.add_argument("--data-dir", type=Path, required=True)
    task.add_argument("--arm", choices=["baseline", "current", "memory", "residual", "lora"], required=True)
    task.add_argument("--model", required=True)
    task.add_argument("--effort", default="high")
    task.add_argument("--user", default="developer_a")
    task.add_argument("--timeout", type=int, default=900)
    report = sub.add_parser("export")
    report.add_argument("--component-run", type=Path, required=True)
    report.add_argument("--reference-run", type=Path, required=True)
    report.add_argument("--task-root", type=Path)
    report.add_argument("--rules-reference", type=Path)
    report.add_argument("--dataset", type=Path)
    report.add_argument("--output", type=Path, required=True)
    rules = sub.add_parser("rules-reference")
    rules.add_argument("--dataset", type=Path, required=True)
    rules.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "dataset":
        from .dataset import write_dataset
        result = write_dataset(args.output)
    elif args.command == "smoke":
        import time
        import psutil
        from .runner import make_engine
        from .dataset import generate
        from rippletide.personalization import atomic_json
        started = time.perf_counter()
        engine = make_engine(args.data_dir, args.model)
        loaded = time.perf_counter() - started
        row = generate()[0]
        result = {"model": args.model, "load_seconds": loaded,
                  "prediction": engine.predict(row["packet"]),
                  "rss_gib": psutil.Process().memory_info().rss / 2**30,
                  "available_gib": psutil.virtual_memory().available / 2**30}
        atomic_json(args.output, result)
    elif args.command == "rules-reference":
        from .rules_reference import run_rules
        result = run_rules(args.dataset, args.output)
    elif args.command == "export":
        from .reporting import export
        result = export(args.component_run, args.reference_run, args.output, args.task_root, args.rules_reference, args.dataset)
    elif args.command == "task":
        from .task_comparison import run_task
        result = run_task(args.output, args.dataset, args.component_run, args.data_dir,
                          arm=args.arm, model=args.model, effort=args.effort, user=args.user, timeout=args.timeout)
    elif args.command == "codex-reference":
        from .codex_reference import run_reference
        result = run_reference(args.dataset, args.output, model=args.model, effort=args.effort,
                               limit=args.limit, train_limit=args.train_limit)
    else:
        from .runner import run
        result = run(args.dataset, args.output, args.data_dir, model=args.model, epochs=args.epochs,
                     rank=args.rank, layers=args.layers, train_limit=args.train_limit,
                     users=args.users, include_lora=not args.without_lora)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
