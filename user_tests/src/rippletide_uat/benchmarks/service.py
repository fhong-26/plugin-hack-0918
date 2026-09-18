"""Allowlisted local MCP fixture tools with transactional state and call evidence."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from jsonschema import Draft202012Validator
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from rippletide_uat.storage import read_json, write_json
from . import ADAPTER_VERSION, case_spec

CLOCK = 1778846400.0  # Fixed UTC fixture clock; never used for elapsed measurements.
MUTATIONS = {"add_product_to_cart", "set_cellular_service_status", "send_message_with_phone_number"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def transport_name(name: str) -> str:
    return name.replace(".", "__")


def initial_state() -> dict:
    return {"clock": CLOCK, "cellular": False, "cart": [], "messages": [],
            "contacts": [{"person_id": "contact-self", "name": "Fixture User", "phone_number": "+12025550100", "relationship": "self", "is_self": True},
                         {"person_id": "contact-fredrik", "name": "Fredrik Thordendal", "phone_number": "+12453344098", "relationship": "friend", "is_self": False},
                         {"person_id": "contact-other", "name": "Alex Example", "phone_number": "+12025550101", "relationship": "friend", "is_self": False}],
            "reminders": [{"reminder_id": f"reminder-{index}", "content": content,
                           "creation_timestamp": CLOCK - 86400, "reminder_timestamp": CLOCK + delta,
                           "latitude": 37.3346, "longitude": -122.009}
                          for index, (delta, content) in enumerate([(-3600, "Return the library book"),
                              (1800, "Buy a nice rich navy bathing dress"), (86400, "Collect the repaired bicycle")])],
            "history": [{"coordinates": [46.603354, 1.888334], "city": "Bourges", "date": "2019-12-13", "temperature_c": 7.25, "wind_speed_kph": 18.5},
                        {"coordinates": [48.8566, 2.3522], "city": "Paris", "date": "2019-12-13", "temperature_c": 8.0, "wind_speed_kph": 12.0}],
            "forecasts": [{"location": city, "metric": metric, "values": [base + day for day in range(14)]}
                          for city, base in (("Boston, USA", 10), ("Rome, Italy", 20))
                          for metric in ("temperature", "humidity", "precipitation")]}


def seed(arm_run: Path, case: str) -> dict:
    """Exclusive creation: an old attempt is never reset or overwritten."""
    spec = case_spec(case)
    arm_run.mkdir(parents=True, exist_ok=True)
    folder = arm_run / "fixture"
    folder.mkdir(mode=0o700)
    state = initial_state()
    with sqlite3.connect(folder / "state.sqlite") as db:
        db.executescript("CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);"
                         "CREATE TABLE events (sequence INTEGER PRIMARY KEY, body TEXT NOT NULL);")
        db.execute("INSERT INTO state VALUES (1,?)", (json.dumps(state),))
    (folder / "state.sqlite").chmod(0o600)
    manifest = {"schema_version": 1, "case": case, "adapter": ADAPTER_VERSION,
                "initial_state_sha256": fingerprint(state), "tools": spec["tools"]}
    write_json(folder / "manifest.json", manifest)
    write_json(folder / "initial-state.json", state)
    return manifest


def _search(rows, arguments, fuzzy=()):
    if not arguments:
        raise ValueError("At least one search criterion is required")
    results = []
    for row in rows:
        match = True
        for key, value in arguments.items():
            if key.endswith("_lowerbound"):
                match &= row[key.removesuffix("_lowerbound")] >= value
            elif key.endswith("_upperbound"):
                match &= row[key.removesuffix("_upperbound")] <= value
            elif key in fuzzy:
                # Disclosed local substring semantics, not ToolSandbox fuzzy scoring.
                match &= value.casefold() in row[key].casefold()
            else:
                match &= row[key] == value
        if match:
            results.append(row)
    return results


def invoke(state: dict, tool: str, args: dict):
    """Real bounded handlers. No network, subprocess, eval, or oracle access."""
    if tool.startswith("weather.get_by_"):
        return [row for row in state["history"] if all(row[key] == value for key, value in args.items())]
    if tool == "weather.get_forecast_by_coordinates":
        days = args.get("days_ahead", 7)
        if not 1 <= days <= 14:
            raise ValueError("Fixture supports 1–14 forecast days")
        if not any(row["coordinates"] == args["coordinates"] for row in state["history"]):
            return []
        return {"coordinates": args["coordinates"], "days_ahead": days,
                "temperature_c": [15.0 + day for day in range(days)], "synthetic": True}
    if tool.startswith("weather_forecast_"):
        if not 1 <= args["days"] <= 14:
            raise ValueError("Fixture supports 1–14 forecast days")
        rows = [row for row in state["forecasts"] if row["location"] == args["location"] and row["metric"] == tool.removeprefix("weather_forecast_")]
        return [{**row, "values": row["values"][:args["days"]]} for row in rows]
    if tool == "add_product_to_cart":
        if args["quantity"] <= 0 or args["product_id"] <= 0:
            raise ValueError("Product and quantity must be positive")
        item = {"cart_id": args.get("cart_id", 0), "product_id": args["product_id"], "quantity": args["quantity"]}
        state["cart"].append(item)
        return item
    if tool == "get_current_timestamp":
        return state["clock"]
    if tool == "shift_timestamp":
        return args["timestamp"] + timedelta(**{key: value for key, value in args.items() if key != "timestamp"}).total_seconds()
    if tool == "timestamp_to_datetime_info":
        date = datetime.fromtimestamp(args["timestamp"], tz=timezone.utc)
        return {**{key: getattr(date, key) for key in ("year", "month", "day", "hour", "minute", "second")}, "isoweekday": date.isoweekday()}
    if tool == "search_reminder":
        return _search(state["reminders"], args, fuzzy=("content",))
    if tool == "search_contacts":
        return _search(state["contacts"], args, fuzzy=("name",))
    if tool == "get_cellular_service_status":
        return state["cellular"]
    if tool == "set_cellular_service_status":
        if state["cellular"] == args["on"]:
            raise ValueError("Cellular service already has that status")
        state["cellular"] = args["on"]
        return None
    if tool == "send_message_with_phone_number":
        if not state["cellular"]:
            raise ConnectionError("Cellular service is off")
        if not args["phone_number"].startswith("+") or not args["content"]:
            raise ValueError("A phone number and nonempty content are required")
        identifier = str(uuid.uuid4())
        state["messages"].append({"message_id": identifier, "recipient_phone_number": args["phone_number"],
                                  "content": args["content"], "timestamp": state["clock"]})
        return identifier
    raise ValueError("Unregistered fixture handler")


class Fixture:
    def __init__(self, arm_run: Path):
        self.folder = arm_run.resolve() / "fixture"
        if self.folder.is_symlink() or self.folder.resolve().parent != arm_run.resolve():
            raise ValueError("Fixture state must remain inside its owned arm directory")
        self.manifest = read_json(self.folder / "manifest.json")
        self.tools = {transport_name(tool["name"]): tool for tool in self.manifest["tools"]}
        expected = case_spec(self.manifest["case"])["tools"]
        if self.manifest["tools"] != expected:
            raise ValueError("Fixture catalog differs from the pinned extraction")
        self.database = self.folder / "state.sqlite"
        if self.database.is_symlink() or not self.database.is_file():
            raise ValueError("A regular owned fixture database is required")

    def snapshot(self):
        with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as db:
            return json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

    def events(self):
        with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY sequence")]

    def call(self, name: str, arguments: dict, *, phase="task") -> dict:
        start = time.perf_counter()
        with sqlite3.connect(self.database.as_uri() + "?mode=rw", uri=True, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            before = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            after = json.loads(json.dumps(before))
            event = {"fixture_call_id": str(uuid.uuid4()), "tool": name, "arguments": arguments,
                     "phase": phase, "result": None, "status": "success", "state_before_sha256": fingerprint(before)}
            try:
                tool = self.tools[name]
                event["tool"] = tool["name"]
                Draft202012Validator(tool["parameters"]).validate(arguments)
                event["result"] = invoke(after, tool["name"], arguments)
            except Exception as exc:
                after = before
                event.update(status="error", error=f"{type(exc).__name__}: {exc}")
            event.update(elapsed_ms=(time.perf_counter() - start) * 1000, state_after_sha256=fingerprint(after))
            db.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(after, allow_nan=False),))
            db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(event, allow_nan=False),))
        return event


async def serve(arm_run: Path):
    fixture = Fixture(arm_run)

    async def list_tools(context, params):
        return ListToolsResult(tools=[Tool(name=name, description=tool["description"], inputSchema=tool["parameters"],
            annotations=ToolAnnotations(read_only_hint=tool["name"] not in MUTATIONS, destructive_hint=False,
                                        idempotent_hint=tool["name"] not in MUTATIONS, open_world_hint=False))
            for name, tool in fixture.tools.items()])

    async def call_tool(context, params):
        event = await asyncio.to_thread(fixture.call, params.name, params.arguments or {})
        value = event.get("error") if event["status"] == "error" else event["result"]
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                              structuredContent={"result": event["result"], "fixture_call_id": event["fixture_call_id"]},
                              isError=event["status"] == "error")

    server = Server("benchmark_fixture", version=ADAPTER_VERSION, on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())
