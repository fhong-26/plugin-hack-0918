"""Public scenario evidence contract, including compatibility with older runs."""

from importlib.resources import files
from pathlib import Path

from .storage import read_json


def expected_evidence(manifest: dict) -> list[str]:
    """Return task checks plus comparison checks without rewriting a manifest."""
    evidence = list(manifest["scenario_definition"]["evidence"])
    if manifest["scenario"] == "U09":
        definitions = read_json(Path(str(files("rippletide_uat") / "assets" / "scenarios.json")))
        evidence.extend(definitions["U09"]["evidence"])
    return list(dict.fromkeys(evidence))
