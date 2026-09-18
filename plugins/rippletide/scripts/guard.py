#!/usr/bin/env python3
"""Local routing guard and evidence observer. Standard library only, no inference.

Hooks are not a security boundary: unsupported host paths are reported separately.
The parent session id is not enough to isolate specialists; include their actual
transcript path and turn. Never add telemetry arguments to third-party tools.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import time


OPERATIONS = {"repository_search", "knowledge_lookup", "specialist_assignment"}
MAX_CORRECTIONS = 2
MAX_RECEIPT_AGE = 300


class UnsupportedShellSyntax(ValueError):
    """A shell program cannot be safely classified by this bounded recognizer."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def project_root(event):
    override = os.environ.get("RIPPLETIDE_PROJECT_ROOT")
    here = Path(override or event.get("cwd") or os.getcwd()).resolve()
    for path in (here, *here.parents):
        if (path / ".rippletide" / "config.json").is_file():
            return path
        if (path / ".git").exists():
            return path
    return here


def read_config(root):
    path = root / ".rippletide" / "config.json"
    return json.loads(path.read_text()) if path.is_file() else None


def observer_config(run_dir, phase):
    """Classify baseline calls without putting router instructions in its project."""
    if phase not in {"preflight", "task"}:
        raise ValueError("Unknown evidence phase")
    path = Path(run_dir) / f"{phase}-registry.json"
    return json.loads(path.read_text()) if path.is_file() else None


def tool_parts(name):
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[1], parts[2]
    tool = name.rsplit(".", 1)[-1]
    # Codex 0.155's v2 surface flattens this namespace without a separator.
    if tool in {"collaborationspawn_agent", "collaborationwait_agent", "collaborationlist_agents"}:
        tool = tool.removeprefix("collaboration")
    return None, tool


def is_router(name):
    server, tool = tool_parts(name)
    return bool(server and (server == "rippletide" or server.endswith("_rippletide"))
                and tool in {"route", "status", "report"})


def command_boundaries(command):
    """Keep unquoted newlines as separators without treating quoted text as code."""
    result, quote, index = [], None, 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            following = command[index + 1]
            if following != "\n":
                result.extend((char, following))
            index += 2
            continue
        if quote:
            result.append(char)
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            result.append(char)
        elif char == "#" and (index == 0 or command[index - 1].isspace() or command[index - 1] in ";&|()"):
            # shlex otherwise consumes the terminating newline with a comment,
            # merging the next executable into the preceding command's args.
            while index < len(command) and command[index] != "\n":
                index += 1
            continue
        else:
            result.append(";" if char == "\n" else char)
        index += 1
    return "".join(result)


def shell_routes(command, depth=0):
    """Recognize explicit search commands, not arbitrary program semantics."""
    if depth > 3:
        return set()
    lexer = shlex.shlex(command_boundaries(command), posix=True, punctuation_chars=";&|()")
    lexer.commenters = ""
    lexer.whitespace_split = True
    segments, segment = [], []
    try:
        tokens = list(lexer)
    except ValueError as exc:
        # Here-document bodies can contain arbitrary quotes and are not shell
        # argument lists. Do not block an unrelated edit as a routing failure.
        raise UnsupportedShellSyntax("Shell wrapper outside recognizer coverage") from exc
    for token in tokens:
        if token and all(char in ";&|()" for char in token):
            if segment:
                segments.append(segment)
            segment = []
        else:
            segment.append(token)
    if segment:
        segments.append(segment)
    routes = set()
    for tokens in segments:
        while tokens and (tokens[0] in {"command", "env"} or "=" in tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue
        executable = Path(tokens[0]).name
        if executable in {"bash", "zsh", "sh"} and len(tokens) > 2 and "c" in tokens[1]:
            routes.update(shell_routes(tokens[2], depth + 1))
        elif executable in {"rg", "ripgrep"}:
            routes.add("native.filename_search" if "--files" in tokens else "native.lexical_search")
        elif executable in {"grep", "egrep", "fgrep"} or (executable == "git" and "grep" in tokens[1:3]):
            routes.add("native.lexical_search")
        elif executable in {"find", "fd", "fdfind"}:
            routes.add("native.filename_search")
    return routes


def classify(name, arguments, capabilities):
    server, tool = tool_parts(name)
    if is_router(name):
        return [], None
    if name == "Bash" or tool in {"exec_command", "shell", "shell_command"}:
        command = arguments.get("command", arguments.get("cmd", ""))
        if isinstance(command, list):
            command = shlex.join(command)
        ids = shell_routes(command) if isinstance(command, str) else set()
        matches = [cap for cap in capabilities if cap["id"] in ids]
        return matches, "repository_search" if ids else None
    matches = []
    for cap in capabilities:
        invocation = cap.get("invocation", {})
        if cap.get("kind") == "mcp" and server and invocation.get("tool") == tool:
            expected = invocation.get("server", "")
            if server == expected or server.endswith("_" + expected):
                matches.append(cap)
        elif cap.get("kind") == "agent" and tool in {"spawn_agent", "Agent"}:
            if invocation.get("agent_type") == arguments.get("agent_type"):
                matches.append(cap)
    operations = {operation for cap in matches for operation in cap.get("operations", []) if operation in OPERATIONS}
    return matches, next(iter(operations)) if len(operations) == 1 else None


def decision_response(value, depth=0):
    if depth > 8:
        return None
    if isinstance(value, str):
        try:
            return decision_response(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return None
    if isinstance(value, dict):
        if isinstance(value.get("decision_id"), str) and value.get("status") in {"selected", "defer"}:
            return value
        for key in ("structuredContent", "result", "content", "text"):
            result = decision_response(value.get(key), depth + 1)
            if result:
                return result
    if isinstance(value, list):
        for item in value:
            result = decision_response(item, depth + 1)
            if result:
                return result
    return None


class Guard:
    def __init__(self, root, run_dir, *, mode="enforce", phase="task"):
        if mode not in {"enforce", "observe"} or phase not in {"task", "preflight", "judge"}:
            raise ValueError("Invalid hook mode or phase")
        self.root, self.run_dir, self.mode, self.phase = Path(root), Path(run_dir), mode, phase
        self.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.run_dir / "routing-receipts.sqlite"
        self.events = self.run_dir / "hook-events.jsonl"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                  scope TEXT, turn_id TEXT, call_id TEXT, request TEXT,
                  PRIMARY KEY(scope,turn_id,call_id));
                CREATE TABLE IF NOT EXISTS receipts (
                  decision_id TEXT PRIMARY KEY, scope TEXT, turn_id TEXT,
                  operation TEXT, route_id TEXT, response TEXT, issued REAL,
                  consumed_by TEXT);
                CREATE TABLE IF NOT EXISTS corrections (
                  scope TEXT, turn_id TEXT, operation TEXT, count INTEGER,
                  PRIMARY KEY(scope,turn_id,operation));
            """)

    def connect(self):
        db = sqlite3.connect(self.database, timeout=2)
        db.row_factory = sqlite3.Row
        return db

    def record(self, event, name, **extra):
        entry = {"schema_version": 1, "event": name,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "session_id": event.get("session_id"), "transcript_path": event.get("transcript_path"),
                 "turn_id": event.get("turn_id"), "call_id": event.get("tool_use_id"),
                 "tool_name": event.get("tool_name"), "tool_input": event.get("tool_input", {}),
                 "phase": self.phase, "mode": self.mode, **extra}
        payload = (json.dumps(entry, ensure_ascii=False) + "\n").encode()
        fd = os.open(self.events, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            while payload:
                payload = payload[os.write(fd, payload):]
        finally:
            os.close(fd)

    def deny(self, event, scope, operation, reason, **extra):
        with self.connect() as db:
            db.execute("INSERT INTO corrections VALUES (?,?,?,1) ON CONFLICT DO UPDATE SET count=count+1",
                       (scope, event.get("turn_id"), operation))
            count = db.execute("SELECT count FROM corrections WHERE scope=? AND turn_id=? AND operation=?",
                               (scope, event.get("turn_id"), operation)).fetchone()[0]
        exhausted = count > MAX_CORRECTIONS
        correction = ("Execute the capability selected by your most recent Rippletide decision, not this different capability. Do not repeat the unchanged routing request."
                      if reason == "SELECTED_CAPABILITY_MISMATCH" else
                      "Call Rippletide route for this immediate goal, wait for its result, then invoke only the selected capability. Split mixed search methods into separate calls. A defer authorizes one fallback in that operation family.")
        message = ("Rippletide routing checks could not be satisfied. Stop this task and report the routing failure; do not retry or bypass it."
                   if exhausted else correction)
        self.record(event, "routing_blocked", operation=operation, reason_code=reason,
                    correction_count=count, exhausted=exhausted, **extra)
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": message}}

    def handle(self, event, config):
        hook = event.get("hook_event_name")
        name, arguments = event.get("tool_name", ""), event.get("tool_input", {})
        arguments = arguments if isinstance(arguments, dict) else {}
        capabilities = (config or {}).get("capabilities", [])
        scope = digest([event.get("session_id"), event.get("transcript_path"), str(self.root)])
        turn, call = event.get("turn_id"), event.get("tool_use_id")
        observed = self.mode == "observe" or self.phase != "task" or config is None
        if hook == "SessionStart":
            self.record(event, "hook_started", configured=config is not None)
            if observed:
                return {}
            return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
                    "Rippletide routing is enabled for this project. Before registered repository searches (including rg --files), MCP information lookups, or named specialist choices, call the installed Rippletide route tool with your immediate goal. Wait for its selection, then supply arguments and execute it. Each decision permits one matching call; a defer permits one fallback. Ordinary direct reads, edits, and tests are not routed. Do not route the router itself. Hooks check this workflow; preserve user permissions."}}
        if hook == "PostToolUse":
            self.record(event, "tool_completed", tool_response=event.get("tool_response"))
            if not is_router(name) or tool_parts(name)[1] != "route":
                return {}
            with self.connect() as db:
                pending = db.execute("SELECT request FROM requests WHERE scope=? AND turn_id=? AND call_id=?",
                                     (scope, turn, call)).fetchone()
                if not pending:
                    self.record(event, "hook_error", reason_code="UNMATCHED_ROUTE_RESULT")
                    return {}
                request = json.loads(pending[0])
                response = decision_response(event.get("tool_response"))
                if response is None:
                    # A completed failed router call permits an explicit, visible fallback.
                    response = {"decision_id": "fallback-" + digest([scope, turn, call]), "status": "defer",
                                "source": "fallback", "reason_code": "ROUTER_CALL_FAILED", "route_id": None}
                operation = request.get("operation")
                if operation not in OPERATIONS or Path(request.get("project_root", "")).resolve() != self.root:
                    self.record(event, "hook_error", reason_code="INVALID_ROUTE_SCOPE")
                    return {}
                if response["status"] == "selected" and response.get("route_id") not in {cap["id"] for cap in capabilities}:
                    self.record(event, "hook_error", reason_code="UNREGISTERED_ROUTE")
                    return {}
                if db.execute("SELECT 1 FROM receipts WHERE decision_id=?", (response["decision_id"],)).fetchone():
                    return {}
                db.execute("UPDATE receipts SET consumed_by=? WHERE scope=? AND turn_id=? AND operation=? AND consumed_by IS NULL",
                           ("superseded:" + response["decision_id"], scope, turn, operation))
                db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?,NULL)",
                           (response["decision_id"], scope, turn, operation, response.get("route_id"),
                            json.dumps(response), time.time()))
                self.record(event, "routing_receipt", decision_id=response["decision_id"],
                            request=request, response=response, operation=operation)
            return {}
        if hook != "PreToolUse":
            return {}
        self.record(event, "tool_proposed")
        if is_router(name):
            if tool_parts(name)[1] == "route":
                with self.connect() as db:
                    db.execute("INSERT OR REPLACE INTO requests VALUES (?,?,?,?)", (scope, turn, call, json.dumps(arguments)))
            return {}
        try:
            matches, operation = classify(name, arguments, capabilities)
        except UnsupportedShellSyntax:
            self.record(event, "uncovered_tool", reason_code="UNSUPPORTED_SHELL_SYNTAX")
            return {}
        if not matches:
            self.record(event, "uncovered_tool", reason_code="UNREGISTERED_OR_OUT_OF_SCOPE", detected_operation=operation)
            return {}
        if observed:
            self.record(event, "tool_observed", capability_ids=[cap["id"] for cap in matches], operation=operation)
            return {}
        if not turn or not call or not event.get("transcript_path"):
            return self.deny(event, scope, operation or "unknown", "MISSING_HOST_IDENTITY")
        if len(matches) != 1 or operation is None:
            return self.deny(event, scope, operation or "repository_search", "AMBIGUOUS_OR_MIXED_CAPABILITIES")
        capability = matches[0]
        if not capability.get("available"):
            return self.deny(event, scope, operation, "CAPABILITY_UNAVAILABLE")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = db.execute("SELECT * FROM receipts WHERE scope=? AND turn_id=? AND operation=? AND consumed_by IS NULL AND issued>? ORDER BY issued DESC LIMIT 1",
                                 (scope, turn, operation, time.time() - MAX_RECEIPT_AGE)).fetchone()
            if receipt is None:
                reason = "MISSING_ROUTING_DECISION"
            elif receipt["route_id"] is not None and receipt["route_id"] != capability["id"]:
                reason = "SELECTED_CAPABILITY_MISMATCH"
            else:
                response = json.loads(receipt["response"])
                db.execute("UPDATE receipts SET consumed_by=? WHERE decision_id=? AND consumed_by IS NULL", (call, receipt["decision_id"]))
                db.execute("DELETE FROM corrections WHERE scope=? AND turn_id=? AND operation=?", (scope, turn, operation))
                self.record(event, "routing_authorized", decision_id=receipt["decision_id"],
                            capability_id=capability["id"], operation=operation,
                            source=response.get("source"), fallback=response.get("status") == "defer")
                return {}
        return self.deny(event, scope, operation, reason, capability_id=capability["id"])


def check_events(path):
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    proposed = {(entry.get("session_id"), entry.get("transcript_path"), entry.get("call_id")): entry
                for entry in events if entry.get("event") == "tool_proposed" and entry.get("phase") == "preflight"}
    verified = {"native": False, "mcp": False, "agent": False}
    for event in events:
        key = (event.get("session_id"), event.get("transcript_path"), event.get("call_id"))
        if event.get("event") != "tool_completed" or event.get("phase") != "preflight" or key not in proposed:
            continue
        server, tool = tool_parts(event.get("tool_name", ""))
        if server == "rippletide_uat_probe" and tool == "ping":
            response = event.get("tool_response")
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except ValueError:
                    response = {}
            if isinstance(response, dict) and response.get("isError") is not True:
                payload = response.get("structuredContent", response.get("structured_content", {}))
                if not payload:
                    for item in response.get("content", []):
                        try:
                            payload = json.loads(item.get("text", ""))
                        except (ValueError, TypeError):
                            continue
                        if isinstance(payload, dict):
                            break
                verified["mcp"] |= isinstance(payload, dict) and payload.get("ready") is True and payload.get("purpose") == "host_hook_preflight"
        elif tool in {"spawn_agent", "Agent"}:
            response = event.get("tool_response")
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except ValueError:
                    response = {}
            verified["agent"] |= isinstance(response, dict) and bool(response.get("agent_id") or response.get("task_name"))
        elif tool in {"Bash", "exec_command", "shell", "shell_command"}:
            verified["native"] |= event.get("tool_response") == "rippletide-ready"
    return {"ready": all(verified.values()), **verified, "evidence": str(path),
            "scope": "native/probe results and specialist spawn; child completion checked separately"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-events", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.check_events:
        result = check_events(args.check_events)
        print(json.dumps(result))
        return 0 if result["ready"] else 1
    event, guard = {}, None
    try:
        event = json.load(sys.stdin)
        root = project_root(event)
        target = os.environ.get("RIPPLETIDE_RUN_DIR")
        config = read_config(root)
        mode = os.environ.get("RIPPLETIDE_HOOK_MODE", "enforce")
        phase = os.environ.get("RIPPLETIDE_PHASE", "task")
        if config is None and target and mode == "observe":
            config = observer_config(target, phase)
        if config is None and not target:
            # Installing the plugin must not collect unrelated project activity.
            print("{}")
            return 0
        run_dir = Path(target) if target else Path.home() / ".local" / "share" / "rippletide" / "hooks" / digest(str(root))[:20]
        guard = Guard(root, run_dir, mode=mode, phase=phase)
        result = guard.handle(event, config)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        if guard:
            try:
                guard.record(event, "hook_error", error_type=type(exc).__name__)
            except Exception:
                pass
        if event.get("hook_event_name") == "PreToolUse" and os.environ.get("RIPPLETIDE_HOOK_MODE", "enforce") == "enforce":
            print("Rippletide routing guard failed; stop and inspect hook readiness.", file=sys.stderr)
            return 2
        print("{}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
