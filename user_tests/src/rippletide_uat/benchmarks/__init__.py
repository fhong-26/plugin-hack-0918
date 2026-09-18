"""Five pinned, benchmark-derived scenarios; no router-private imports."""

from pathlib import Path
from rippletide_uat.storage import read_json

ADAPTER_VERSION = "benchmark-fixtures-v1"
CASE_IDS = ("B01", "B02", "B03", "B04", "B05")


def catalog() -> dict:
    return read_json(Path(__file__).parent / "catalog.json")


def case_spec(case: str) -> dict:
    if case not in CASE_IDS:
        raise ValueError(f"Unknown benchmark case: {case}")
    return catalog()["cases"][case]
