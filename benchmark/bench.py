# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9,<4"]
# ///
"""Fifty real tool-choice cases, two choosers, three plots. No task execution."""

import argparse
import asyncio
import csv
import hashlib
import json
import math
import shlex
import signal
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = HERE / "data"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def tasks():
    manifest = json.loads((DATA / "manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        if sha(DATA / name) != expected:
            raise ValueError(f"Frozen benchmark changed: {name}")
    return read_rows(DATA / "tasks.jsonl")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def summarize(result):
    """Grade only completed evidence. Missing/invalid choices always count wrong."""
    cases = tasks()
    if result.get("benchmark_sha256") != sha(DATA / "tasks.jsonl"):
        raise ValueError("Results belong to a different benchmark")
    gold = {r["id"]: r["tool_id"] for r in read_rows(DATA / "answers.jsonl")}
    ids = [case["id"] for case in cases]
    summaries, details, names = [], [], set()
    if not result.get("systems"):
        raise ValueError("No systems in results")
    for system in result["systems"]:
        name = system["name"]
        if name in names:
            raise ValueError(f"Duplicate system name: {name}")
        names.add(name)
        predictions = system["predictions"]
        if [row["id"] for row in predictions] != ids:
            raise ValueError(f"{name}: require all 50 cases once in stored order")
        correct, invalid, times, costs = 0, 0, [], []
        for case, row in zip(cases, predictions):
            valid = not row.get("error") and isinstance(row.get("tool_id"), str) and row["tool_id"] in {t["id"] for t in case["input"]["tools"]}
            hit = valid and row["tool_id"] == gold[case["id"]]
            correct += bool(hit)
            invalid += not valid
            elapsed, cost = row.get("elapsed_s"), row.get("cost_usd")
            if elapsed is not None and not number(elapsed):
                raise ValueError(f"{name}/{case['id']}: invalid elapsed_s")
            if cost is not None and not number(cost):
                raise ValueError(f"{name}/{case['id']}: invalid cost_usd")
            if elapsed is not None:
                times.append(elapsed)
            if cost is not None:
                costs.append(cost)
            details.append({"system": name, "id": case["id"], "family": case["family"],
                            "expected": gold[case["id"]], "selected": row.get("tool_id"),
                            "correct": bool(hit), "error": row.get("error"),
                            "elapsed_s": elapsed, "cost_usd": cost})
        summaries.append({"name": name, "correct": correct, "total": len(cases), "invalid": invalid,
                          "accuracy": correct / len(cases),
                          "median_s": statistics.median(times) if len(times) == len(cases) else None,
                          "timed_cases": len(times), "priced_cases": len(costs),
                          "total_cost_usd": sum(costs) if len(costs) == len(cases) else None})
    return summaries, details


def plot(result, out):
    summaries, details = summarize(result)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    colors = ["#b35c32", "#246a73", "#7067a8", "#597d38"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False})
    specs = [
        ("correctness", "Correct tool choice", "Higher is better", "Correct (%)", "accuracy", 100),
        ("price", "Price of 50 choices", "Lower is better", "Estimated remote model API cost (USD)", "total_cost_usd", 1),
        ("speed", "Median choice time", "Lower is better", "Seconds", "median_s", 1),
    ]
    for filename, title, hint, ylabel, key, scale in specs:
        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor("#fafafa")
        ax.set_facecolor("#fafafa")
        values = [s[key] * scale if s[key] is not None else 0 for s in summaries]
        bars = ax.bar(range(len(summaries)), values, color=[colors[i % len(colors)] for i in range(len(summaries))], width=.55, zorder=3)
        labels = []
        for s, bar in zip(summaries, bars):
            if s[key] is None:
                labels.append("N/A")
                bar.set_hatch("///")
            elif key == "accuracy":
                labels.append(f"{s['correct']}/{s['total']} ({s['accuracy']:.0%})")
            elif key == "total_cost_usd":
                labels.append(f"${s[key]:.2f}")
            else:
                labels.append(f"{s[key]:.2f} s")
        ax.bar_label(bars, labels=labels, padding=8, fontweight="bold")
        ax.set_ylim(0, 118 if key == "accuracy" else max(max(values, default=0) * 1.25, .1))
        ax.set_xticks(range(len(summaries)), [s["name"].replace(" (", "\n(") for s in summaries])
        ax.tick_params(axis="x", length=0, pad=10)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{title}\n{hint}", loc="left", fontweight="bold", pad=18)
        ax.yaxis.grid(True, color="#dddddd", linewidth=.6, zorder=0)
        if key == "accuracy":
            ax.set_yticks([0, 20, 40, 60, 80, 100])
        note = "50 real-tool cases · one choice each · no abstention or scenario execution"
        if key == "total_cost_usd":
            note += "\nAPI-equivalent estimate; local hardware and surrounding agent costs excluded."
            if any(s[key] is None for s in summaries):
                note += "\nN/A means missing pricing/usage, not zero cost."
        elif key == "median_s":
            note += "\nAll attempts, including errors; adapter timing boundaries are recorded in results."
            if any(s[key] is None for s in summaries):
                note += "\nN/A means some cases were not timed; no partial median is shown."
        else:
            note += "\nSynthetic development pilot; GPT-6 authored/reviewed cases may favor that family."
        invalid = [f"{s['name']}: {s['invalid']} invalid/error" for s in summaries if s["invalid"]]
        if invalid:
            note += "\n" + "; ".join(invalid)
        fig.text(.09, .035, note, fontsize=8, color="#555555", va="bottom")
        fig.subplots_adjust(left=.12, right=.97, bottom=.28, top=.81)
        fig.savefig(out / f"{filename}.png", dpi=180, facecolor=fig.get_facecolor())
        plt.close(fig)
    with (out / "cases.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)
    (out / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    return summaries


async def stop(process):
    if process.returncode is None:
        try:
            import os
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            import os
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


async def line(process, timeout):
    raw = await asyncio.wait_for(process.stdout.readline(), timeout)
    if not raw:
        raise RuntimeError("Chooser exited without a response; inspect its stderr log")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("Chooser must return a JSON object")
    return response


async def run_system(name, command, cases, out, timeout):
    """One persistent chooser. Pass only input, never case labels or answers."""
    rows = []
    started = time.perf_counter()
    with (out / f"{name.lower()}.stderr.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(*command, cwd=REPO, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=log, limit=8 * 1024 * 1024, start_new_session=True)
        try:
            ready = await line(process, timeout)
            if ready.get("ready") is not True:
                raise RuntimeError(f"{name} startup failed: {ready.get('error', ready)}")
            system = {"name": name, "command": command, "metadata": ready.get("metadata", {}),
                      "startup_s": time.perf_counter() - started, "predictions": rows}
            fatal = None
            with (out / f"{name.lower()}.jsonl").open("x") as evidence:
                for i, case in enumerate(cases):
                    inp = json.dumps(case["input"], ensure_ascii=False, separators=(",", ":"))
                    record = {"id": case["id"], "input_sha256": hashlib.sha256(inp.encode()).hexdigest(),
                              "tool_id": None, "elapsed_s": None, "cost_usd": None, "error": fatal}
                    if not fatal:
                        tick = time.perf_counter()
                        try:
                            async with asyncio.timeout(timeout):
                                process.stdin.write((inp + "\n").encode())
                                await process.stdin.drain()
                                response = await line(process, timeout)
                            record.update({k: response.get(k) for k in ["tool_id", "elapsed_s", "cost_usd", "error"]})
                            record["wall_s"] = time.perf_counter() - tick
                            record["response"] = response
                            if record["elapsed_s"] is not None and not number(record["elapsed_s"]):
                                record.update(elapsed_s=None, error="invalid_timing")
                            if record["cost_usd"] is not None and not number(record["cost_usd"]):
                                record.update(cost_usd=None, error="invalid_price")
                            if not isinstance(record["tool_id"], str) or record["tool_id"] not in {t["id"] for t in case["input"]["tools"]}:
                                record["error"] = record["error"] or "invalid_tool_id"
                            if response.get("fatal"):
                                record["error"] = record["error"] or "chooser_failure"
                                fatal = "not_run_after_chooser_failure"
                                await stop(process)
                        except (TimeoutError, ValueError, RuntimeError, BrokenPipeError, ConnectionResetError) as exc:
                            record.update(elapsed_s=time.perf_counter() - tick, error=f"{type(exc).__name__}: {exc}")
                            fatal = "not_run_after_chooser_failure"
                            await stop(process)
                    rows.append(record)
                    evidence.write(json.dumps(record, ensure_ascii=False) + "\n")
                    evidence.flush()
                    print(f"{name}: {i + 1}/{len(cases)} {record['tool_id'] or record['error']}", flush=True)
            return system
        finally:
            await stop(process)


async def run(args):
    cases = tasks()  # The answer key is hashed, but not parsed before inference.
    out = args.out or HERE / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    router = shlex.split(args.router_command) if args.router_command else [
        "uv", "run", "--locked", "--project", str(REPO / "plugins/rippletide"),
        "python", str(HERE / "adapters/rippletide.py"), "--model", args.router_model]
    codex = [sys.executable, str(HERE / "adapters/codex.py"), "--model", args.codex_model, "--effort", args.effort]
    result = {"schema_version": 1, "benchmark_sha256": sha(DATA / "tasks.jsonl"),
              "recorded_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Conditional next-tool selection, one sequential pass per system, no task execution.",
              "systems": []}
    print(f"Writing {out}\nFresh Codex inference may incur charges. Selection only; observed tool attempts fail the run.")
    for name, command in [("Router" if args.router_command else "Rippletide", router), ("Codex", codex)]:
        result["systems"].append(await run_system(name, command, cases, out, args.timeout))
        (out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    plot(result, out)
    print(f"Done: {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command")
    plots = subs.add_parser("plot", help="Plot saved results; no model calls (the default)")
    plots.add_argument("--input", type=Path, default=HERE / "example/results.json")
    plots.add_argument("--out", type=Path, default=HERE / "results")
    fresh = subs.add_parser("run", help="Compare this repo's Rippletide with Codex on all 50 cases")
    fresh.add_argument("--out", type=Path)
    fresh.add_argument("--router-model", default="qwen25-rlcd")
    fresh.add_argument("--codex-model", default="gpt-6-astra")
    fresh.add_argument("--effort", default="high")
    fresh.add_argument("--router-command", help="Optional argv string for another JSON-lines chooser")
    fresh.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    try:
        if args.command == "run":
            if not number(args.timeout) or args.timeout == 0:
                parser.error("--timeout must be positive")
            asyncio.run(run(args))
        else:
            source = getattr(args, "input", HERE / "example/results.json")
            out = getattr(args, "out", HERE / "results")
            summary = plot(json.loads(source.read_text()), out)
            print(json.dumps(summary, indent=2))
            print(f"Plots: {out.resolve()}")
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        parser.exit(1, f"Benchmark error: {exc}\n")


if __name__ == "__main__":
    main()
