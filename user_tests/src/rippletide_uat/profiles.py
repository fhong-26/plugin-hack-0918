"""Explicit, credential-free project profiles for paired experiments."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .storage import read_json, timestamp, write_json


MODEL_OPTIONS = ("qwen25-rlcd", "qwen3-0.6b", "minicpm5-2b", "qwen3.5-4b")
OPERATIONS = {"repository_search", "knowledge_lookup", "specialist_assignment"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def data_root() -> Path:
    return Path(os.environ.get("RIPPLETIDE_UAT_DATA_DIR", str(Path.home() / ".local/share/rippletide/uat"))).expanduser().resolve()


def repo_root(repo: Path) -> Path:
    value = subprocess.run(["git", "-C", str(repo.expanduser().resolve()), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(value.stdout.strip()).resolve()


def profile_path(repo: Path) -> Path:
    identity = hashlib.sha256(str(repo_root(repo)).encode()).hexdigest()[:20]
    return data_root() / "profiles" / f"{identity}.json"


def argv_value(value: str) -> list[str]:
    command = json.loads(value)
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError("Commands must be nonempty JSON argv arrays, not shell strings")
    return command


def validate_tool_config(config: dict) -> dict:
    """A narrow allowlist prevents accidentally importing a personal Codex config.

    Values in env/headers are intentionally unsupported. Secrets are referenced
    by environment-variable name, never stored in profiles or report manifests.
    User-approved commands themselves are trusted executable configuration.
    """
    if not isinstance(config, dict) or set(config) - {"mcp_servers", "capabilities", "agents", "preferences", "environment_names", "mcp_preflight", "benchmark_fixture"}:
        raise ValueError("Tool config permits only mcp_servers, capabilities, agents, preferences, environment_names and mcp_preflight")
    result = {"mcp_servers": {}, "capabilities": [], "agents": {}, "preferences": {}, "environment_names": [], "mcp_preflight": {}}
    result.update(config)
    if result.get("benchmark_fixture"):
        from .benchmarks.runner import validate_fixture_profile
        validate_fixture_profile(result)
    for name in result["environment_names"]:
        if not isinstance(name, str) or not ENV_NAME.fullmatch(name):
            raise ValueError("environment_names must contain environment-variable names only")
    for name, server in result["mcp_servers"].items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name == "rippletide":
            raise ValueError("MCP names must be simple identifiers; rippletide is reserved")
        if not isinstance(server, dict) or set(server) - {"command", "args", "cwd", "env_vars", "url", "bearer_token_env_var", "enabled_tools", "startup_timeout_sec", "tool_timeout_sec"}:
            raise ValueError(f"Unsupported or inline-secret MCP configuration for {name}")
        if bool(server.get("command")) == bool(server.get("url")):
            raise ValueError(f"MCP {name} must have exactly one command or url")
        if not server.get("enabled_tools") or not all(isinstance(tool, str) for tool in server["enabled_tools"]):
            raise ValueError(f"MCP {name} requires an explicit read-only enabled_tools allowlist")
        for variable in [*server.get("env_vars", []), *([server["bearer_token_env_var"]] if server.get("bearer_token_env_var") else [])]:
            if not ENV_NAME.fullmatch(variable):
                raise ValueError(f"MCP {name} authentication must reference environment-variable names")
        if server.get("url"):
            from urllib.parse import urlsplit
            url = urlsplit(server["url"])
            if url.scheme not in {"https", "http"} or url.username or url.password or url.query or url.fragment:
                raise ValueError("MCP URLs must have no embedded credentials, query or fragment")
    for server, call in result["mcp_preflight"].items():
        if (server not in result["mcp_servers"] or not isinstance(call, dict)
                or set(call) != {"tool", "arguments"} or not isinstance(call["arguments"], dict)
                or call["tool"] not in result["mcp_servers"][server]["enabled_tools"]):
            raise ValueError("MCP host preflight requires one explicitly allowlisted read-only tool and an arguments object")
    seen = set()
    for entry in result["capabilities"]:
        required = {"id", "kind", "operations", "description", "invocation", "input_schema"}
        if not isinstance(entry, dict) or not required <= set(entry):
            raise ValueError("Capabilities require id, kind, operations, description, invocation and input_schema")
        if entry["id"] in seen or not entry["id"].startswith(("mcp.", "agent.")):
            raise ValueError("Configured capability IDs must be unique mcp.* or agent.* identifiers")
        seen.add(entry["id"])
        operations = OPERATIONS | ({"fixture_tool_use"} if result.get("benchmark_fixture") else set())
        if not entry["operations"] or set(entry["operations"]) - operations:
            raise ValueError("Unsupported capability operation")
        invocation = entry["invocation"]
        if entry["kind"] == "mcp":
            server = result["mcp_servers"].get(invocation.get("server"), {})
            if invocation.get("tool") not in server.get("enabled_tools", []):
                raise ValueError("MCP capability must map to an explicitly enabled read-only tool")
        elif entry["kind"] == "agent":
            if invocation.get("agent_type") not in result["agents"]:
                raise ValueError("Agent capability must map to an approved specialist")
        else:
            raise ValueError("Native search registrations are provided by the runner")
    for name, agent in result["agents"].items():
        if name in {"max_threads", "max_depth", "job_max_runtime_seconds"} or not re.fullmatch(r"[A-Za-z0-9_-]+", name) or set(agent) - {"description", "config_file"} or not agent.get("description") or not agent.get("config_file"):
            raise ValueError("Agents require description and config_file only")
        path = Path(agent["config_file"]).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Missing approved specialist file: {path}")
        import tomllib
        definition = tomllib.loads(path.read_text())
        if set(definition) - {"name", "description", "developer_instructions"}:
            raise ValueError("Specialists must inherit parent settings: only name, description and developer_instructions allowed")
        agent["config_file"] = str(path)
    return result


def configure(repo: Path, *, bootstrap: list[list[str]] | None = None, checks: list[list[str]] | None = None,
              independent_checks: list[list[str]] | None = None,
              tool_config: Path | None = None, model: str | None = None, effort: str | None = None,
              replace: bool = False) -> dict:
    root = repo_root(repo)
    destination = profile_path(root)
    if destination.exists() and not replace:
        raise FileExistsError(f"Profile exists: {destination}; use --replace to update it explicitly")
    tools = validate_tool_config(read_json(tool_config) if tool_config else default_tools())
    profile = {"schema_version": 1, "repo": str(root), "created_at": timestamp(),
               "bootstrap": bootstrap or [], "checks": checks or [], "independent_checks": independent_checks or [], "tools": tools,
               "model": model, "effort": effort, "sandbox": "workspace-write",
               "approval_policy": "never", "external_access": "read_only_allowlist",
               "acceptance": "configured" if checks or independent_checks else "ungraded"}
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(destination, profile)
    destination.chmod(0o600)
    return {"profile": str(destination), **profile,
            "note": "Only explicitly configured tools are loaded. Check commands determine acceptance; missing checks remain ungraded."}


def default_tools() -> dict:
    agents, capabilities = {}, []
    for role, description in (("reviewer", "Inspect a bounded change for concrete implementation regressions."),
                              ("test_specialist", "Inspect coverage, run relevant tests and identify missing regression cases.")):
        name = f"rippletide_{role}"
        agents[name] = {"description": description, "config_file": str(Path(__file__).parent / "assets/agents" / f"{name}.toml")}
        capabilities.append({"id": f"agent.{role}", "kind": "agent", "operations": ["specialist_assignment"],
                             "description": description, "invocation": {"agent_type": name},
                             "input_schema": {"type": "object", "properties": {"agent_type": {"const": name}, "message": {"type": "string"}}, "required": ["agent_type", "message"]}})
    return {"agents": agents, "capabilities": capabilities}


def load_profile(repo: Path) -> dict:
    path = profile_path(repo)
    if not path.is_file():
        raise FileNotFoundError(f"Configure this project first: rippletide-uat configure --repo {repo_root(repo)}")
    profile = read_json(path)
    if profile.get("schema_version") != 1 or profile.get("repo") != str(repo_root(repo)):
        raise ValueError("Unsupported profile or mismatched repository")
    profile["tools"] = validate_tool_config(profile.get("tools", {}))
    return profile
