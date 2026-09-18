#!/usr/bin/env python3
"""Stage an owned personal plugin using the installed Codex plugin-creator helpers."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    source = repo / "plugins" / "rippletide"
    target = Path.home() / "plugins" / "rippletide"
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    helpers = codex_home / "skills" / ".system" / "plugin-creator" / "scripts"
    marker = target / ".rippletide-source.json"
    marketplace = Path.home() / ".agents" / "plugins" / "marketplace.json"
    for required in (source / "uv.lock", source / "pyproject.toml", helpers / "create_basic_plugin.py",
                     helpers / "read_marketplace_name.py", helpers / "update_plugin_cachebuster.py"):
        if not required.is_file():
            parser.error(f"Required file is missing: {required}")
    uv = shutil.which("uv")
    codex = shutil.which("codex")
    if not uv or not codex:
        parser.error("uv and codex must be available on PATH")
    if target.exists():
        if not marker.is_file() or json.loads(marker.read_text()).get("source") != str(source):
            parser.error(f"Refusing to replace a plugin not owned by this checkout: {target}")
    if marketplace.exists():
        # The personal marketplace helper validates the identifier before edits
        # or constructing an installation command; do not rewrite this catalog.
        subprocess.run([sys.executable, str(helpers / "read_marketplace_name.py")], check=True)
        catalog = json.loads(marketplace.read_text())
        entries = [entry for entry in catalog["plugins"] if entry["name"] == "rippletide"]
        if entries and entries[0].get("source") != {"source": "local", "path": "./plugins/rippletide"}:
            parser.error("The personal marketplace's Rippletide entry points at another source")
        if target.exists() and len(entries) != 1:
            parser.error("Existing staged plugin requires exactly one matching personal marketplace entry")
    print(json.dumps({"source": str(source), "target": str(target), "marketplace": str(marketplace), "dry_run": args.dry_run}), flush=True)
    if args.dry_run:
        return 0

    def helper(name, *arguments):
        return subprocess.run([sys.executable, str(helpers / name), *map(str, arguments)], check=True, text=True)

    helper_python = [uv, "run", "--no-project", "--python", "3.12", "--with", "pyyaml==6.0.3", "python"]
    subprocess.run([*helper_python, str(helpers / "validate_plugin.py"), str(source)], check=True)
    existing = target.exists()
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = target.with_name(f"rippletide-backup-{stamp}")
        target.rename(backup)
        print(f"Previous owned plugin preserved at {backup}", flush=True)
        target.mkdir(parents=True)
    else:
        helper("create_basic_plugin.py", "rippletide", "--with-skills", "--with-mcp", "--with-marketplace")
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "*.egg-info", "tests"))
    marker.write_text(json.dumps({"source": str(source)}, indent=2) + "\n")
    helper("update_plugin_cachebuster.py", target)
    subprocess.run([*helper_python, str(helpers / "validate_plugin.py"), str(target)], check=True)
    name = subprocess.check_output([sys.executable, str(helpers / "read_marketplace_name.py")], text=True).strip()
    # The default personal marketplace is discovered implicitly. Do not use
    # marketplace list/add as a test or registration step for this flow.
    subprocess.run([codex, "plugin", "add", f"rippletide@{name}"], check=True)
    print("Installed Rippletide. Start a fresh Codex session to load the updated skill and tools.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
