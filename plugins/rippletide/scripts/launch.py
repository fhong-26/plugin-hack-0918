#!/usr/bin/env python3
"""Launch from the installed plugin copy, independently of the caller's cwd."""

import os
from pathlib import Path
import shutil
import sys


def main():
    uv = shutil.which("uv")
    if uv is None:
        print("Rippletide requires uv on PATH. See the project README for setup.", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    extra = ["--extra", "cpu-lab"] if os.environ.get("RIPPLETIDE_MODEL") == "qwen3-0.6b-torch" else []
    os.execv(uv, [uv, "run", "--frozen", "--python", "3.12", "--project", str(root), *extra, "rippletide", "serve"])


if __name__ == "__main__":
    sys.exit(main())
