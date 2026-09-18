"""Explicit project registration and preferences; repository text is never policy."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefer: dict[str, str] = Field(default_factory=dict)
    exclude: list[str] = Field(default_factory=list)
    exact_symbol_first: bool | None = None


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    kind: Literal["native", "mcp", "agent"]
    operations: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    available: bool
    invocation: dict[str, Any]
    input_schema: dict[str, Any]
    availability: dict[str, Any] | None = None


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    registry_version: str = "v1"
    run_id: str | None = None
    phase: Literal["preflight", "task", "acceptance", "grading"] = "task"
    variant: Literal["A", "B", "C", "D"] = "D"
    fixture_mode: bool = False
    log_path: str | None = None
    preferences: Preferences = Field(default_factory=Preferences)
    capabilities: list[Capability] = Field(default_factory=list)


def builtin_capabilities() -> list[dict]:
    available = shutil.which("rg") is not None
    return [
        {
            "id": "native.filename_search", "kind": "native",
            "operations": ["repository_search"],
            "description": "Find files when a filename, path, extension or file naming pattern is known.",
            "available": available,
            "invocation": {"tool": "exec_command", "command_hint": "rg --files"},
            "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "workdir": {"type": "string"}}, "required": ["cmd"]},
        },
        {
            "id": "native.lexical_search", "kind": "native",
            "operations": ["repository_search"],
            "description": "Find exact text, symbols, error messages or implementation keywords inside source files.",
            "available": available,
            "invocation": {"tool": "exec_command", "command_hint": "rg -n"},
            "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "workdir": {"type": "string"}}, "required": ["cmd"]},
        },
    ]


def global_preferences_path() -> Path:
    return Path.home() / ".config" / "rippletide" / "preferences.json"


def load_config(project_root: str) -> tuple[ProjectConfig, Preferences, Path]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")
    path = root / ".rippletide" / "config.json"
    if path.exists():
        config = ProjectConfig.model_validate_json(path.read_text())
    else:
        config = ProjectConfig(capabilities=builtin_capabilities())
    ids = [cap.id for cap in config.capabilities]
    if len(ids) != len(set(ids)):
        raise ValueError("capability IDs must be unique")
    global_path = global_preferences_path()
    global_pref = Preferences.model_validate_json(global_path.read_text()) if global_path.exists() and not config.fixture_mode else Preferences()
    effective = Preferences(
        prefer={**global_pref.prefer, **config.preferences.prefer},
        exclude=list(dict.fromkeys(global_pref.exclude + config.preferences.exclude)),
        exact_symbol_first=(config.preferences.exact_symbol_first
            if config.preferences.exact_symbol_first is not None
            else global_pref.exact_symbol_first if global_pref.exact_symbol_first is not None else True),
    )
    return config, effective, root


def is_available(capability: Capability) -> bool:
    if not capability.available:
        return False
    preflight = capability.availability or {}
    if preflight.get("status") in {"unavailable", "failed", "blocked", "error"}:
        return False
    if preflight.get("available") is False:
        return False
    return True


def update_preferences(project_root: str, update: dict) -> dict:
    """Only the explicit CLI preference command persists changes."""
    patch = Preferences.model_validate(update).model_dump(exclude_unset=True)
    config, _, root = load_config(project_root)
    previous = config.preferences.model_dump(exclude_none=True)
    if "prefer" in patch:
        patch["prefer"] = {**previous.get("prefer", {}), **patch["prefer"]}
    config.preferences = Preferences.model_validate({**previous, **patch})
    path = root / ".rippletide" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace one complete config atomically; preserve registration and run metadata.
    fd, temporary = tempfile.mkstemp(prefix=".preferences-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(config.model_dump_json(indent=2, exclude_none=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"saved": True, "path": str(path), "preferences": config.preferences.model_dump(exclude_none=True)}
