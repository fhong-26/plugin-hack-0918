"""Conservative, public-artifact-only Codex trace normalization.

Raw rollouts are authoritative when present. CLI JSONL is a fallback, never an
additional bill. No reasoning items, reasoning summaries, or hidden state are read.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
import shlex

from .storage import digest

TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")


def instant(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def path_at(run: Path, value) -> Path | None:
    if not isinstance(value, (str, Path)) or not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else run / path


def events_at(path: Path | None) -> tuple[list[dict], list[str]]:
    if path is None or not path.is_file():
        return [], ["missing_artifact"]
    events, warnings = [], []
    for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
            else:
                warnings.append(f"non_object_line:{number}")
        except json.JSONDecodeError:
            warnings.append(f"invalid_json_line:{number}")
    return events, warnings


def json_value(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        if "\nOutput:\n" in value:
            try:
                return json.loads(value.split("\nOutput:\n", 1)[1])
            except json.JSONDecodeError:
                pass
        return None


def own_events(events: list[dict]) -> tuple[list[dict], dict, list[str]]:
    if events and all(instant(e.get("timestamp")) is not None for e in events):
        events = sorted(events, key=lambda e: instant(e["timestamp"]))
    metas = [e.get("payload", {}) for e in events if e.get("type") == "session_meta"]
    meta = metas[0] if metas else {}
    created = instant(meta.get("timestamp"))
    child = isinstance(meta.get("source"), dict) or meta.get("thread_source") == "subagent"
    warnings = []
    result, seen = [], set()
    own_turns = {e.get("payload", {}).get("turn_id") for e in events
                 if e.get("type") == "token_usage_record" and e.get("payload", {}).get("thread_id") == meta.get("id")}
    inherited_segment = False
    for event in events:
        identity = digest(event)
        if identity in seen:
            continue
        seen.add(identity)
        when = instant(event.get("timestamp"))
        payload = event.get("payload") or {}
        if child and event.get("type") == "session_meta":
            inherited_segment = payload.get("id") != meta.get("id")
            if inherited_segment:
                continue
        if child and event.get("type") == "event_msg" and payload.get("type") == "task_started":
            began = payload.get("started_at")
            if payload.get("turn_id") in own_turns:
                inherited_segment = False
            elif isinstance(began, (int, float)) and created is not None:
                inherited_segment = began < int(created)
            elif inherited_segment:
                warnings.append("child_history_boundary_unknown")
        if child and inherited_segment:
            continue
        # Copied history in forked agents is not another executed call or bill.
        if child and created is not None and when is not None and when < created:
            continue
        if child and event.get("type") != "session_meta" and (created is None or when is None):
            warnings.append("child_history_boundary_unknown")
            continue
        result.append(event)
    return result, meta, sorted(set(warnings))


def native_routes(command, depth=0) -> set[str]:
    if not isinstance(command, str) or depth > 3:
        return set()
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        segments, current = [], []
        for token in lexer:
            if token and all(x in ";&|()" for x in token):
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)
    except ValueError:
        return set()
    routes = set()
    for tokens in segments:
        while tokens and (tokens[0] in {"command", "env"} or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0])):
            tokens.pop(0)
        if not tokens:
            continue
        binary = Path(tokens[0]).name
        if binary in {"sh", "bash", "zsh"} and len(tokens) > 2 and "c" in tokens[1]:
            routes |= native_routes(tokens[2], depth + 1)
        elif binary in {"rg", "ripgrep"}:
            routes.add("filename_search" if "--files" in tokens else "lexical_search")
        elif binary in {"grep", "egrep", "fgrep"} or binary == "git" and "grep" in tokens[1:3]:
            routes.add("lexical_search")
        elif binary in {"find", "fd", "fdfind"}:
            routes.add("filename_search")
    return routes


def tool_kind(name: str, args: dict) -> str:
    if name.startswith("mcp__"):
        server = name.split("__")[1]
        return "routing" if server == "rippletide" or server.endswith("_rippletide") else "mcp"
    short = name.rsplit(".", 1)[-1]
    if short.startswith("collaboration"):
        short = short.removeprefix("collaboration")
    if short in {"spawn_agent", "followup_task", "send_message_to_thread"}:
        return "agent"
    if short in {"wait", "wait_agent", "close_agent", "send_message", "list_agents"}:
        return "orchestration"
    if short in {"exec_command", "shell_command", "shell", "Bash"}:
        routes = native_routes(args.get("cmd", args.get("command", "")))
        if routes:
            return next(iter(routes)) if len(routes) == 1 else "mixed_search"
        return "command"
    return "other"


def outcome(name, args, output, observed=True) -> dict:
    if not observed:
        return {"status": "unknown", "reason": "no_tool_output", "exit_code": None}
    parsed = json_value(output)
    kind = tool_kind(name, args)
    error = None
    code = parsed.get("exit_code") if isinstance(parsed, dict) else None
    if kind in {"command", "filename_search", "lexical_search", "mixed_search"}:
        match = re.search(r"Process exited with code (-?\d+)", str(output))
        if code is None and match:
            code = int(match.group(1))
        if code is not None:
            # rg status 1 means a valid completed search with no matches.
            search_no_matches = kind == "lexical_search" or (kind == "filename_search" and bool(re.search(r"\brg\s+--files\b", str(args))))
            ok = code == 0 or (code == 1 and search_no_matches)
            return {"status": "success" if ok else "failure", "exit_code": code,
                    "reason": "no_matches" if code == 1 and ok else "process_exit"}
    if isinstance(parsed, dict):
        if parsed.get("isError") or parsed.get("is_error") or parsed.get("error"):
            error = True
        elif kind == "agent":
            # Spawning is not a completed specialist assignment.
            return {"status": "unknown", "reason": "spawn_only", "exit_code": None,
                    "child_id": parsed.get("agent_id"), "child_path": parsed.get("task_name")}
        elif kind in {"mcp", "routing", "orchestration"}:
            error = False
    if re.search(r"(?i)(user cancelled|tool call failed|error calling tool|unknown agent_type)", str(output)):
        error = True
    return {"status": "failure" if error is True else "success" if error is False else "unknown",
            "reason": "tool_result" if error is not None else "unrecognized_result", "exit_code": code}


def normalize_raw(events: list[dict], fallback_id: str) -> dict:
    events, meta, warnings = own_events(events)
    session = meta.get("id") or fallback_id
    calls, observations, final_messages = {}, [], []
    turn = None
    completed_children = set()
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        when = event.get("timestamp")
        if event.get("type") == "event_msg" and payload.get("type") == "task_started":
            turn = payload.get("turn_id")
        if event.get("type") != "response_item":
            continue
        typ = payload.get("type")
        if typ == "message" and payload.get("role") in {"user", "assistant"}:
            content = "\n".join(str(x.get("text", "")) for x in payload.get("content", [])
                                if x.get("type") in {"input_text", "output_text"})
            if content:
                if payload["role"] == "user":
                    observations.append({"type": "user_message", "index": index, "timestamp": when, "text": content})
                elif payload.get("channel") != "analysis":
                    final_messages.append(content)
        if typ in {"function_call", "custom_tool_call"}:
            name = payload.get("name", "unknown")
            namespace = payload.get("namespace", "")
            name = namespace + name if namespace.startswith("mcp__") else name
            args = json_value(payload.get("arguments"))
            if not isinstance(args, dict):
                args = {"input": payload.get("input", payload.get("arguments"))}
            call_id = payload.get("call_id") or f"missing-{index}"
            calls[call_id] = {"call_id": call_id, "session_id": session, "turn_id": turn,
                              "timestamp": when, "index": index, "tool_name": name,
                              "arguments": args, "kind": tool_kind(name, args),
                              "outcome": outcome(name, args, None, False), "result": None,
                              "context_before": list(observations), "format": "raw"}
        elif typ in {"function_call_output", "custom_tool_call_output"}:
            call = calls.get(payload.get("call_id"))
            if call is None:
                warnings.append("orphan_tool_output")
                continue
            output = payload.get("output")
            call.update(result=output, completed_at=when,
                        outcome=outcome(call["tool_name"], call["arguments"], output))
            observations.append({"type": "tool_result", "index": index, "timestamp": when,
                                 "call_id": call["call_id"], "tool_name": call["tool_name"], "result": output})
            parsed = json_value(output)
            if isinstance(parsed, dict):
                for child, state in (parsed.get("status") or {}).items() if isinstance(parsed.get("status"), dict) else []:
                    if isinstance(state, dict) and "completed" in state:
                        completed_children.add(child)
    for call in calls.values():
        if call["outcome"].get("child_id") in completed_children:
            call["outcome"].update(status="success", reason="structured_agent_completion")
    for call in calls.values():
        if call["tool_name"] == "exec" and call["arguments"].get("input"):
            call["kind"] = "host_container"
    return {"session_id": session, "meta": meta, "events": events, "calls": list(calls.values()),
            "final_messages": final_messages, "warnings": sorted(set(warnings)), "format": "raw"}


def normalize_cli(events: list[dict], fallback_id: str) -> dict:
    session = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), fallback_id)
    calls, final_messages, observations = {}, [], []
    for index, event in enumerate(events):
        item = event.get("item") or {}
        if event.get("type") not in {"item.started", "item.completed"}:
            continue
        if item.get("type") == "agent_message":
            final_messages.append(item.get("text", ""))
            continue
        typ = item.get("type")
        args = json_value(item.get("arguments")) or {}
        if typ == "command_execution":
            name, args = "exec_command", {"cmd": item.get("command", "")}
            result = {"exit_code": item.get("exit_code"), "output": item.get("aggregated_output")}
        elif typ == "mcp_tool_call":
            name = f"mcp__{item.get('server', 'unknown')}__{item.get('tool', 'unknown')}"
            result = item.get("result")
            if item.get("error"):
                result = {"error": item["error"]}
        elif typ == "collab_tool_call":
            name = item.get("tool", "unknown")
            args = {**args, "agent_type": item.get("agent_type"), "message": item.get("prompt")}
            result = {"agent_id": next(iter(item.get("receiver_thread_ids", [])), None)} if name == "spawn_agent" else None
        else:
            continue
        identity = item.get("id") or f"missing-{index}"
        call = calls.setdefault(identity, {"call_id": identity, "session_id": session, "turn_id": event.get("turn_id"),
                                          "timestamp": item.get("timestamp") or event.get("timestamp"), "index": index,
                                          "tool_name": name, "arguments": args, "kind": tool_kind(name, args),
                                          "context_before": list(observations), "format": "cli"})
        call.update(result=result, outcome=outcome(name, args, result, event["type"] == "item.completed"))
        if event["type"] == "item.completed":
            observations.append({"type": "tool_result", "call_id": identity, "tool_name": name, "result": result, "index": index})
    return {"session_id": session, "meta": {}, "events": events, "calls": list(calls.values()),
            "final_messages": final_messages, "warnings": ["cli_context_partial"], "format": "cli"}


def numeric_usage(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    values = {key: value[key] for key in TOKEN_KEYS if isinstance(value.get(key), int) and not isinstance(value[key], bool) and value[key] >= 0}
    return values or None


def sum_usage(values: list[dict]) -> dict | None:
    if not values:
        return None
    keys = set.intersection(*(set(v) for v in values))
    return {key: sum(v[key] for v in values) for key in TOKEN_KEYS if key in keys} or None


def session_usage(session: dict) -> dict:
    events = session["events"]
    warnings = list(session["warnings"])
    complete = not any(x in warnings for x in ("child_history_boundary_unknown", "missing_artifact"))
    if session["format"] == "cli":
        turns = [e for e in events if e.get("type") == "turn.completed"]
        values = [numeric_usage(e.get("usage")) for e in turns]
        # No raw cumulative counter and no explicit turn IDs: multiple turns
        # could be cumulative resume snapshots. Do not add unverifiable bills.
        if len(turns) > 1 and not all(e.get("turn_id") for e in turns):
            warnings.append("cli_multiple_turn_usage_semantics_unknown")
            values = []
        elif turns and all(e.get("turn_id") for e in turns):
            values = list({e["turn_id"]: numeric_usage(e.get("usage")) for e in turns}.values())
        complete = complete and bool(values) and all(v is not None for v in values)
        usage = sum_usage([v for v in values if v])
        return {"usage": usage, "complete": complete, "basis": "cli_turns", "warnings": warnings}
    started = {e["payload"].get("turn_id") for e in events if e.get("type") == "event_msg" and e.get("payload", {}).get("type") == "task_started"}
    ended = {e["payload"].get("turn_id") for e in events if e.get("type") == "event_msg" and e.get("payload", {}).get("type") == "task_complete"}
    records = {}
    last_counter = None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") != "token_usage_record" or payload.get("thread_id") != session["session_id"]:
            continue
        response_id = payload.get("response_id")
        value = numeric_usage(payload.get("usage"))
        if response_id and value:
            if response_id in records and records[response_id] != value:
                warnings.append("conflicting_response_usage")
            records[response_id] = value
            last_counter = numeric_usage(payload.get("thread_token_usage"))
    if records:
        total = sum_usage(list(records.values()))
        verified = bool(total and last_counter and all(total.get(k) == v for k, v in last_counter.items()))
        if not verified:
            warnings.append("response_usage_coverage_unproven")
        if not started or not started <= ended:
            warnings.append("session_completion_unproven")
        return {"usage": total, "complete": complete and verified and bool(started) and started <= ended and not warnings,
                "basis": "unique_thread_response_ids", "warnings": sorted(set(warnings))}
    snapshots = []
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total, last = numeric_usage(info.get("total_token_usage")), numeric_usage(info.get("last_token_usage"))
            if total:
                snapshots.append((total, last))
    contributions, previous = [], None
    for total, last in snapshots:
        if previous == total:
            continue
        if previous is None:
            if last == total:
                contributions.append(total)
            else:
                complete = False
                warnings.append("initial_usage_balance_unknown")
                if last:
                    contributions.append(last)
        elif set(previous) == set(total) and all(total[k] >= previous[k] for k in total):
            delta = {k: total[k] - previous[k] for k in total}
            contributions.append(delta)
            if last is not None and any(delta.get(k) != v for k, v in last.items()):
                complete = False
                warnings.append("missing_intermediate_usage_snapshots")
        elif total == last:
            contributions.append(total)
        else:
            complete = False
            warnings.append("usage_counter_reset_unresolved")
            if last:
                contributions.append(last)
        previous = total
    if not started or not started <= ended:
        complete = False
        warnings.append("session_completion_unproven")
    if not contributions:
        complete = False
        warnings.append("missing_usage")
    return {"usage": sum_usage(contributions), "complete": complete, "basis": "deduplicated_session_counter_deltas",
            "warnings": sorted(set(warnings))}


def arm_traces(run: Path, arm: dict) -> dict:
    raw_paths = [arm.get("parent_rollout"), *arm.get("child_rollouts", [])]
    grouped, warnings = defaultdict(list), []
    for value in raw_paths:
        if not value:
            continue
        events, errors = events_at(path_at(run, value))
        warnings.extend(errors)
        sid = next((e.get("payload", {}).get("id") for e in events if e.get("type") == "session_meta"), str(value))
        grouped[sid].extend(events)
    sessions = [normalize_raw(events, sid) for sid, events in grouped.items() if events]
    parent_path = path_at(run, arm.get("parent_rollout"))
    if not parent_path or not parent_path.is_file():
        events, errors = events_at(path_at(run, arm.get("session_path")))
        warnings.extend(errors)
        if events:
            fallback = normalize_cli(events, "parent-unknown")
            sessions = [fallback, *[s for s in sessions if s["session_id"] != fallback["session_id"]]]
    if sessions:
        accepted = {sessions[0]["session_id"]}
        changed = True
        while changed:
            changed = False
            for session in sessions[1:]:
                metadata = session["meta"]
                source = metadata.get("source") if isinstance(metadata.get("source"), dict) else {}
                parent = metadata.get("parent_thread_id") or source.get("subagent", {}).get("thread_spawn", {}).get("parent_thread_id")
                if parent in accepted and session["session_id"] not in accepted:
                    accepted.add(session["session_id"])
                    changed = True
        if any(s["session_id"] not in accepted for s in sessions):
            warnings.append("unrelated_or_unproven_child_rollout")
        sessions = [s for s in sessions if s["session_id"] in accepted]
    calls = [call for session in sessions for call in session["calls"]]
    calls.sort(key=lambda x: (instant(x.get("timestamp")) is None, instant(x.get("timestamp")) or 0, x["index"]))
    link_children(calls, sessions)
    expected_children = {c["outcome"].get("child_id") for c in calls if c["outcome"].get("child_id")}
    present = {s["session_id"] for s in sessions}
    missing = sorted(expected_children - present)
    if missing:
        warnings.append("missing_child_rollouts")
    unresolved_children = [c for c in calls if c["outcome"].get("child_path") and not c["outcome"].get("child_id")]
    if unresolved_children:
        warnings.append("unresolved_child_task_paths")
    usages = [{"session_id": s["session_id"], **session_usage(s)} for s in sessions]
    return {"sessions": sessions, "calls": calls, "warnings": sorted(set(warnings)),
            "usage": {"tokens": sum_usage([u["usage"] for u in usages if u["usage"]]),
                      "complete": bool(usages) and all(u["complete"] for u in usages) and not missing and not warnings,
                      "scope": "observed_parent_and_children", "sessions": usages,
                      "missing_child_sessions": missing,
                      "note": "Cached input is a subset of input; reasoning output is a subset of output. Do not add categories together."}}


def link_children(calls, sessions):
    for call in calls:
        child_path = call["outcome"].get("child_path")
        child_id = call["outcome"].get("child_id")
        if not child_path and not child_id:
            continue
        candidates = []
        for session in sessions:
            meta = session["meta"]
            source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
            spawn = source.get("subagent", {}).get("thread_spawn", {})
            actual_path = meta.get("agent_path") or spawn.get("agent_path")
            parent = meta.get("parent_thread_id") or spawn.get("parent_thread_id")
            role = meta.get("agent_role") or spawn.get("agent_role")
            if parent != call["session_id"] or role != call["arguments"].get("agent_type"):
                continue
            if (child_id and child_id == session["session_id"]) or (child_path and child_path == actual_path):
                candidates.append(session)
        if len(candidates) == 1:
            child = candidates[0]
            call["outcome"]["child_id"] = child["session_id"]
            starts = {e["payload"].get("turn_id") for e in child["events"] if e.get("type") == "event_msg" and e.get("payload", {}).get("type") == "task_started"}
            ends = {e["payload"].get("turn_id") for e in child["events"] if e.get("type") == "event_msg" and e.get("payload", {}).get("type") == "task_complete"}
            if starts and starts <= ends:
                call["outcome"].update(status="success", reason="child_metadata_and_structured_completion")


def hook_calls(traces: dict, hooks: list[dict]) -> list[dict]:
    """Expand concrete host calls hidden by generic exec; do not decode its code.

    Hook proposal/completion IDs are the actual nested IDs. Ambiguous scopes or
    duplicate proposals are not merged. Existing raw calls remain authoritative.
    """
    result = list(traces["calls"])
    existing = {(c["session_id"], c["call_id"]) for c in result}
    for index, event in enumerate(hooks):
        if event.get("event") != "tool_proposed" or not event.get("call_id"):
            continue
        candidates = [s for s in traces["sessions"] if s["session_id"] in str(event.get("transcript_path", ""))]
        if not candidates:
            candidates = [s for s in traces["sessions"] if s["session_id"] == event.get("session_id")]
        if len(candidates) != 1:
            continue
        sid = candidates[0]["session_id"]
        identity = (sid, event["call_id"])
        if identity in existing:
            continue
        existing.add(identity)
        args = event.get("tool_input") or {}
        name = event.get("tool_name") or "unknown"
        matching = [e for e in hooks if all(e.get(k) == event.get(k) for k in ("session_id", "transcript_path", "turn_id", "call_id"))]
        outputs = [e for e in matching if e.get("event") == "tool_completed"]
        when = instant(event.get("timestamp"))
        before = []
        for call in result:
            ended = instant(call.get("completed_at"))
            if call["session_id"] == sid and when is not None and ended is not None and ended <= when and call["kind"] != "host_container":
                before.append({"type": "tool_result", "timestamp": call.get("completed_at"), "tool_name": call["tool_name"], "result": call["result"]})
        value = outputs[0].get("tool_response") if len(outputs) == 1 else None
        result.append({"call_id": event["call_id"], "session_id": sid, "turn_id": event.get("turn_id"),
                       "timestamp": event.get("timestamp"), "completed_at": outputs[0].get("timestamp") if len(outputs) == 1 else None,
                       "index": index, "tool_name": name, "arguments": args, "kind": tool_kind(name, args),
                       "context_before": before, "result": value, "outcome": outcome(name, args, value, len(outputs) == 1), "format": "hook"})
    link_children(result, traces["sessions"])
    result.sort(key=lambda c: (instant(c.get("timestamp")) is None, instant(c.get("timestamp")) or 0, c["index"]))
    for call in result:
        when = instant(call.get("timestamp"))
        if when is None:
            continue
        original_users = [o for o in call["context_before"] if o.get("type") == "user_message"]
        previous = [{"type": "tool_result", "timestamp": other.get("completed_at"), "call_id": other["call_id"],
                     "tool_name": other["tool_name"], "result": other["result"]}
                    for other in result if other["session_id"] == call["session_id"] and other["kind"] != "host_container"
                    and other["call_id"] != call["call_id"] and instant(other.get("completed_at")) is not None
                    and instant(other["completed_at"]) <= when]
        call["context_before"] = sorted([*original_users, *previous], key=lambda o: instant(o.get("timestamp")) or 0)
    return result


def _shell_command(value):
    try:
        tokens = shlex.split(value)
        while len(tokens) >= 3 and Path(tokens[0]).name in {"sh", "bash", "zsh"} and "c" in tokens[1]:
            tokens = shlex.split(tokens[2])
        return tokens
    except (ValueError, TypeError):
        return None


def supplement_cli_outcomes(run, arm, calls):
    """Use a unique exact command+output match for missing nested shell statuses.

    Generic exec hooks expose the exact command/result but not its exit code. CLI
    command_execution provides it. Repeated identical calls are ambiguous and
    remain unknown; this never links routing by fuzzy proximity.
    """
    events, errors = events_at(path_at(run, arm.get("session_path")))
    if errors:
        return
    cli = normalize_cli(events, "cli")["calls"]
    for call in calls:
        if call["format"] != "hook" or call["outcome"]["status"] != "unknown" or call["kind"] not in {"command", "filename_search", "lexical_search", "mixed_search"}:
            continue
        command = _shell_command(call["arguments"].get("cmd", call["arguments"].get("command", "")))
        if command is None:
            continue
        same_hooks = [c for c in calls if c["format"] == "hook" and _shell_command(c["arguments"].get("cmd", c["arguments"].get("command", ""))) == command and c.get("result") == call.get("result")]
        matches = [c for c in cli if c["kind"] in {"command", "filename_search", "lexical_search", "mixed_search"}
                   and _shell_command(c["arguments"].get("cmd", "")) == command and isinstance(c.get("result"), dict)
                   and c["result"].get("output") == call.get("result") and c["outcome"].get("exit_code") is not None]
        if len(matches) == len(same_hooks) == 1:
            call["outcome"] = {**matches[0]["outcome"], "evidence": "unique_exact_hook_cli_command_and_result", "cli_item_id": matches[0]["call_id"]}
