"""Benchmark entry points reusing the paired host, not a second agent runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

from rippletide_uat.storage import write_json
from . import ADAPTER_VERSION, CASE_IDS, case_spec, catalog
from .service import Fixture, fingerprint, seed, transport_name

FIXTURE_BOUNDARY = """Complete the user's request using the connected benchmark_fixture tools.
These tools operate on isolated synthetic local data, not real accounts, weather services,
shopping carts, or messaging providers. Perform only actions warranted by the user request.
Do not use web search, external providers, shell/code execution, or other agents for this task.
Do not read/edit the project, fixture implementation/state files, private logs or graders.
Use returned tool results to answer; report unavailable capabilities or failures honestly.
Do not ask a human for information already obtainable from these tools.
"""


def tool_profile(case: str, run="{run}") -> dict:
    tools = case_spec(case)["tools"]
    return {"benchmark_fixture": case,
            "mcp_servers": {"benchmark_fixture": {"command": sys.executable,
                "args": ["-I", "-m", "rippletide_uat", "benchmark", "serve", "--run", str(run)],
                "enabled_tools": [transport_name(tool["name"]) for tool in tools]}},
            "capabilities": [{"id": "mcp.fixture." + tool["name"], "kind": "mcp", "operations": ["fixture_tool_use"],
                              "description": tool["description"].split("\n\n", 1)[0],
                              "invocation": {"server": "benchmark_fixture", "tool": transport_name(tool["name"])},
                              "input_schema": tool["parameters"]} for tool in tools],
            "agents": {}, "preferences": {}, "environment_names": [], "mcp_preflight": {}}


def validate_fixture_profile(profile: dict):
    """No user-provided executable, URL, credential, agent or answer preference."""
    expected = tool_profile(profile["benchmark_fixture"])
    if profile != expected:
        raise ValueError("Benchmark mode requires exactly the built-in synthetic fixture profile")


def verify_fixture_transport(servers: dict, case: str, arm_run: Path):
    if arm_run is None or servers != tool_profile(case, arm_run)["mcp_servers"]:
        raise ValueError("Fixture write permission cannot be used with another command, URL or tool catalog")
    fixture = Fixture(Path(arm_run))
    if fixture.manifest["case"] != case:
        raise ValueError("Fixture case mismatch")


def implementation_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(json.dumps(catalog(), sort_keys=True).encode())
    return digest.hexdigest()


def product_identity() -> dict:
    from rippletide_uat.paired_host import project_root
    root = project_root()
    digest = hashlib.sha256()
    for folder in ("plugins/rippletide", "user_tests/src", "tools/codex"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and not any(part in {".venv", "__pycache__", ".pytest_cache", "node_modules"} or part.endswith(".egg-info") for part in path.parts):
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    return {"commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
            "runtime_tree_sha256": digest.hexdigest(),
            "dirty": bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip())}


def prepare(case: str, *, output_root: Path | None = None, mode="parallel", router_model="qwen25-rlcd", model=None, effort=None):
    from rippletide_uat.paired import prepare_pair
    from rippletide_uat.paired_host import project_root
    from rippletide_uat.profiles import configure, data_root
    spec = case_spec(case)
    if mode not in {"parallel", "sequential"}:
        raise ValueError("Unsupported experiment mode")
    destination = (output_root or data_root() / "benchmarks").expanduser().resolve()
    if destination.is_relative_to(project_root()):
        raise ValueError("Benchmark runs must remain outside tracked source")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    experiment = destination / f"benchmark-{case}-{uuid.uuid4().hex[:12]}"
    experiment.mkdir(mode=0o700)
    source = experiment / "source"
    source.mkdir()
    (source / "README.md").write_text("# Synthetic tool task\n\nUse only the connected fixture tools for the supplied request.\n")
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Rippletide fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Synthetic benchmark workspace"], check=True, capture_output=True)
    profile_path = experiment / "tools.json"
    write_json(profile_path, tool_profile(case))
    configure(source, tool_config=profile_path, model=model, effort=effort)
    run, manifest = prepare_pair(source, spec["prompt"], output_root=experiment / "runs", mode=mode, router_model=router_model)
    for name in manifest["arms"]:
        seeded = seed(run / name, case)
        manifest["arms"][name]["fixture_initial_state_sha256"] = seeded["initial_state_sha256"]
    manifest.update(benchmark_case=case, benchmark_adapter=ADAPTER_VERSION,
                    benchmark_product=product_identity(),
                    benchmark_implementation_sha256=implementation_hash(),
                    benchmark_catalog_sha256=fingerprint(catalog()),
                    benchmark_source={key: spec[key] for key in ("benchmark", "revision", "entry_id", "source_path", "source_entry_sha256")},
                    status="prepared", official_benchmark_score=None,
                    benchmark_adaptations=catalog()["adaptations"])
    write_json(run / "pair.json", manifest)
    write_json(run / "benchmark-source.json", spec)
    return run, manifest


def run_cases(cases, *, repeat=1, output_root=None, mode="parallel", router_model="qwen25-rlcd",
              model=None, effort=None, codex=None, timeout=180, preflight_timeout=180):
    from rippletide_uat.paired import execute_pair
    from .grading import report
    if not cases or set(cases) - set(CASE_IDS) or len(set(cases)) != len(cases):
        raise ValueError("Choose distinct B01–B05 cases")
    if not 1 <= repeat <= 10 or min(timeout, preflight_timeout) <= 0:
        raise ValueError("Repeat must be 1–10 and timeouts must be positive")
    results = []
    for repetition in range(repeat):
        for case in cases:
            run, manifest = prepare(case, output_root=output_root, mode=mode, router_model=router_model, model=model, effort=effort)
            manifest.update(repetition=repetition + 1, repeat=repeat)
            write_json(run / "pair.json", manifest)
            execute_pair(run, manifest, codex=codex, timeout=timeout, preflight_timeout=preflight_timeout,
                         judge=False, reverse=repetition % 2 == 1)
            result = report(run)
            results.append({"case": case, "run": str(run), "status": manifest["status"],
                            "report": str(run / "benchmark-report.md"), "results": result["results"]})
            if manifest["status"] in {"cancelled", "setup-blocked"}:
                return {"runs": results, "stopped": "Shared setup prerequisite failed; retained the blocked attempt"}
    return {"runs": results, "official_benchmark_validated": False}
