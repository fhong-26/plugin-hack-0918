#!/usr/bin/env python3
"""Build the pinned Codex CLI with Jev selection, without changing global Codex."""

import argparse
from pathlib import Path
import subprocess

REVISION = "f0a1b8f0849d90960bc406b848f32e5a129b0457"  # rust-v0.155.0
ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Fetch and apply the patch without compiling")
    args = parser.parse_args()
    source = ROOT / "build" / "codex-host"
    patch = ROOT / "tools" / "codex" / "jev.patch"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--branch=rust-v0.155.0",
                        "https://github.com/openai/codex.git", str(source)], check=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != REVISION:
        raise SystemExit(f"Expected Codex {REVISION}; found {revision}. Use a fresh build/codex-host directory.")
    check = subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, capture_output=True)
    if check.returncode == 0:
        subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
    else:
        # Repeated builds are safe; never reset an existing checkout.
        subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=source, check=True)
    if not args.prepare_only:
        subprocess.run(["cargo", "build", "--release", "-p", "codex-cli"], cwd=source / "codex-rs", check=True)
        print(source / "codex-rs" / "target" / "release" / "codex")


if __name__ == "__main__":
    main()
