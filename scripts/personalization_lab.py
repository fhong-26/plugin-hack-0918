"""Repository-local launcher, without installing or changing the user's plugin."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "plugins/rippletide/src"), str(ROOT / "experiments")]

if __name__ == "__main__":
    from personalization_lab.cli import main
    main()
