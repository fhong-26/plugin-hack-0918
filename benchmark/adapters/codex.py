#!/usr/bin/env python3
"""Persistent JSONL chooser using the real Codex app-server (Python 3.11+).

--check performs initialization and read-only checks only; it never starts a turn.
Normal mode reads task.input objects from stdin. No gold labels are opened.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import tomllib

BENCHMARK = Path(__file__).resolve().parents[1]
FEATURES_OFF = (
    "apps", "shell_tool", "multi_agent", "multi_agent_v2", "browser_use",
    "browser_use_external", "computer_use", "image_generation", "code_mode",
    "memories", "hooks", "goals", "sleep_tool", "view_image", "workspace_dependencies",
    "default_mode_request_user_input", "request_permissions_tool", "unbounded_connection_retries",
)
PASSIVE_ITEMS = {"userMessage", "agentMessage", "reasoning", "plan", "contextCompaction"}
USAGE_FIELDS = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens",
                "outputTokens", "reasoningOutputTokens", "totalTokens")


def is_decision(name):
    return any(word in name.lower() for word in ("decision", "rippletide"))


def controls_for(config, controls):
    """Inspect names only; never copy credentials into flags or output."""
    for name in config.get("mcp_servers") or {}:
        controls[("mcp_servers", name, "enabled")] = False
    for name in config.get("plugins") or {}:
        if is_decision(name):
            controls[("plugins", name, "enabled")] = False


def initial_controls(args):
    controls = {("features", key): False for key in FEATURES_OFF}
    controls.update({("model",): args.model, ("model_reasoning_effort",): args.effort,
                     ("service_tier",): "default", ("web_search",): "disabled"})
    path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    controls_for(tomllib.loads(path.read_text()) if path.exists() else {}, controls)
    return controls


def dotted(path):
    # The CLI splits override paths on dots; it does not parse quoted TOML keys.
    if any("." in part for part in path):
        raise ValueError("Cannot safely override a configuration name containing a dot")
    return ".".join(path)


def toml_value(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key) + "=" + toml_value(item) for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(map(toml_value, value)) + "]"
    return json.dumps(value)


def cost_for(usage, model, pricing):
    """API-equivalent short-context estimate, never the user's observed bill."""
    usage["cost_basis"] = "API-equivalent; short-context pricing assumed"
    keys = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens")
    if model != pricing.get("model") or any(key not in usage for key in keys):
        usage["cost_unavailable_reason"] = "Unknown model pricing or incomplete cache accounting"
        return None
    total, read, write, output = (usage[key] for key in keys)
    if read + write > total:
        usage["cost_unavailable_reason"] = "Cache read/write counts exceed input tokens"
        return None
    rates = pricing.get("short_context_per_million_tokens", {})
    if any(key not in rates for key in ("uncached_input", "cache_read_input", "cache_write_input", "output")):
        usage["cost_unavailable_reason"] = "Missing price rates"
        return None
    usage["uncachedInputTokens"] = total - read - write
    return ((total - read - write) * rates["uncached_input"] + read * rates["cache_read_input"]
            + write * rates["cache_write_input"] + output * rates["output"]) / 1_000_000


class AppServer:
    def __init__(self, args, cwd, controls):
        self.args, self.cwd, self.controls = args, cwd, controls
        self.seq, self.proc, self.active = 0, None, None
        self.reset_case()

    def reset_case(self):
        self.usage, self.finals, self.legacy_finals = {}, [], []
        self.completed = None

    async def __aenter__(self):
        command = [self.args.codex, "app-server", "--stdio"]
        for key, value in self.controls.items():
            command += ["-c", dotted(key) + "=" + toml_value(value)]
        # Never enable trace logging: it can contain private model reasoning.
        env = dict(os.environ, RUST_LOG="error")
        self.proc = await asyncio.create_subprocess_exec(
            *command, cwd=self.cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=sys.stderr,
            limit=16 * 1024 * 1024)
        try:
            async with asyncio.timeout(self.args.timeout):
                self.initialized = await self.request("initialize", {
                    "clientInfo": {"name": "portable-tool-choice-benchmark", "version": "1.0"},
                    "capabilities": {"experimentalApi": True, "optOutNotificationMethods": [
                        "item/reasoning/textDelta", "item/reasoning/summaryTextDelta",
                        "item/agentMessage/delta"]}})
                await self.send({"method": "initialized"})
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

    async def send(self, message):
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()

    async def receive(self):
        line = await self.proc.stdout.readline()
        if not line:
            raise RuntimeError("Codex app-server exited")
        message = json.loads(line)
        method, params = message.get("method"), message.get("params", {})
        if method and "id" in message:
            await self.send({"id": message["id"], "error": {
                "code": -32601, "message": "Benchmark rejects interactive requests and tools"}})
            raise RuntimeError("Rejected server request: " + method)
        if method in ("model/rerouted", "model/verification"):
            raise RuntimeError("Rejected " + method)
        if method == "error":
            raise RuntimeError("Codex error: " + json.dumps(params.get("error")))
        if not self.active or params.get("threadId", self.active) != self.active:
            return message
        if method in ("item/started", "item/completed"):
            item = params["item"]
            kind = item.get("type")
            if kind not in PASSIVE_ITEMS:
                raise RuntimeError("Rejected tool/unknown item: " + str(kind))
            if kind == "agentMessage" and item.get("memoryCitation"):
                raise RuntimeError("Rejected memory citation")
            if kind == "agentMessage" and method == "item/completed":
                if item.get("phase") == "final_answer":
                    self.finals.append(item.get("text", ""))
                elif item.get("phase") is None:
                    self.legacy_finals.append(item.get("text", ""))
        elif method == "thread/tokenUsage/updated":
            raw = params["tokenUsage"]["total"]
            self.usage = {key: raw[key] for key in USAGE_FIELDS if key in raw
                          and type(raw[key]) is int and raw[key] >= 0}
        elif method == "turn/completed":
            self.completed = params["turn"]
        # Reasoning blocks/deltas are discarded and never included in results.
        return message

    async def request(self, method, params):
        self.seq += 1
        request_id = self.seq
        await self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = await self.receive()
            if message.get("id") == request_id and not message.get("method"):
                if "error" in message:
                    raise RuntimeError(method + ": " + json.dumps(message["error"]))
                return message["result"]

    async def thread(self, extra_config=None):
        session = await self.request("thread/start", {
            "cwd": self.cwd, "ephemeral": True, "approvalPolicy": "never",
            "approvalsReviewer": "user", "sandbox": "read-only", "model": self.args.model,
            "serviceTier": "default", "allowProviderModelFallback": False,
            "config": extra_config or {"model_reasoning_effort": self.args.effort}})
        expected = {"model": self.args.model, "reasoningEffort": self.args.effort,
                    "serviceTier": "default", "approvalPolicy": "never"}
        if any(session.get(key) != value for key, value in expected.items()):
            raise RuntimeError("Effective model/effort/tier/approval settings do not match")
        sandbox = session.get("sandbox", {})
        if not session["thread"].get("ephemeral") or sandbox.get("type") != "readOnly" or sandbox.get("networkAccess"):
            raise RuntimeError("Expected ephemeral read-only thread without sandbox network")
        return session

    async def inventory(self, thread_id):
        servers, cursor = [], None
        while True:
            page = await self.request("mcpServerStatus/list", {
                "threadId": thread_id, "cursor": cursor, "limit": 100})
            servers.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                return servers

    async def config(self):
        return (await self.request("config/read", {"cwd": self.cwd, "includeLayers": False}))["config"]

    async def verify_no_mcp(self, thread_id):
        for server in await self.inventory(thread_id):
            if server.get("tools") or server.get("runtimeStatus") != "disabled":
                raise RuntimeError("An executable or initializing MCP server remains")


async def discover(args, cwd, controls):
    """No model turn: discover process-only overrides, preserving saved auth."""
    async with AppServer(args, cwd, controls) as app, asyncio.timeout(args.timeout):
        config = await app.config()
        controls_for(config, controls)
        session = await app.thread({dotted(key): value for key, value in controls.items()})
        for server in await app.inventory(session["thread"]["id"]):
            prefix = ("plugins", server["pluginId"], "mcp_servers") if server.get("pluginId") else ("mcp_servers",)
            controls[(*prefix, server["name"], "enabled")] = False
        skills = await app.request("skills/list", {"cwds": [cwd], "forceReload": True})
        disabled = list((config.get("skills") or {}).get("config", []))
        for group in skills.get("data", []):
            for skill in group.get("skills", []):
                if is_decision(skill.get("name", "")) and skill.get("enabled", True):
                    disabled.append({"path": skill["path"], "enabled": False})
        if disabled:
            controls[("skills", "config")] = disabled


async def preflight(app):
    config = await app.config()
    for path, value in app.controls.items():
        actual = config
        for part in path:
            actual = actual.get(part, {}) if isinstance(actual, dict) else None
        if actual != value:
            raise RuntimeError("Process control not effective: " + dotted(path))
    account = (await app.request("account/read", {"refreshToken": False})).get("account")
    if not account:
        raise RuntimeError("Persisted Codex account is unavailable; no login was attempted")
    live_auth_read = False
    if account.get("type") == "chatgpt":
        await app.request("account/rateLimits/read", {})
        live_auth_read = True
    session = await app.thread()
    await app.verify_no_mcp(session["thread"]["id"])
    return {"adapter": "codex-app-server", "model": app.args.model, "effort": app.args.effort,
            "service_tier": "default", "cli_version": session["thread"].get("cliVersion"),
            "ephemeral": True, "executable_mcp_tools": 0, "model_turns_started": 0,
            "elapsed_s_scope": "turn/start through turn/completed; excludes fresh-thread setup",
            "cost_basis": "API-equivalent short-context estimate; assumes short-context pricing",
            "account_type": account.get("type"), "live_authenticated_read": live_auth_read,
            "auth_note": "Inference validity is untested; no authentication was changed"}


async def choose(app, line, wrapper, pricing):
    turn_started = None
    finished, validated, invalid_output = None, False, False
    result = {"tool_id": None, "elapsed_s": None, "cost_usd": None, "usage": {}, "error": None}
    app.reset_case()
    try:
        case = json.loads(line)
        if not isinstance(case, dict) or set(case) != {"instruction", "context", "host_instructions", "tools"}:
            raise ValueError("Expected the complete task.input object")
        candidates = [tool["id"] for tool in case["tools"]]
        if not candidates or any(not isinstance(tool, str) or not tool for tool in candidates) or len(set(candidates)) != len(candidates):
            raise ValueError("Expected nonempty, unique candidate tool IDs")
        validated = True
        async with asyncio.timeout(app.args.timeout):
            session = await app.thread()
            app.active = session["thread"]["id"]
            await app.verify_no_mcp(app.active)
            turn_started = time.perf_counter()
            await app.request("turn/start", {"threadId": app.active,
                "input": [{"type": "text", "text": wrapper + line.rstrip("\r\n")}]})
            while app.completed is None:
                await app.receive()
            finished = time.perf_counter()
            if app.completed.get("status") != "completed":
                raise RuntimeError("Turn failed: " + json.dumps(app.completed.get("error") or app.completed.get("status")))
        finals = app.finals or app.legacy_finals
        if len(finals) != 1 or finals[0].strip() not in candidates:
            invalid_output = True
            raise ValueError("Invalid output: expected exactly one supplied tool ID")
        result["tool_id"] = finals[0].strip()
    except Exception as exc:
        finished = finished or time.perf_counter()
        result["error"] = type(exc).__name__ + ": " + (str(exc) or "Codex case timed out")
        if validated and not invalid_output:
            result["fatal"] = True
            await app.close()  # No retry or background continuation after a failed turn.
    finally:
        app.active = None
        result["elapsed_s"] = finished - turn_started if turn_started else None
        result["usage"] = app.usage
        if app.completed and app.completed.get("status") == "completed" and not result.get("fatal"):
            result["cost_usd"] = cost_for(result["usage"], app.args.model, pricing)
        else:
            result["usage"]["cost_unavailable_reason"] = "Turn did not complete; usage may be partial"
    return result


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


async def main(args):
    controls = initial_controls(args)
    wrapper = (Path(__file__).with_name("wrapper.txt")).read_text() if not args.check else ""
    pricing_path = BENCHMARK / "pricing.json"
    pricing = json.loads(pricing_path.read_text()) if pricing_path.exists() else {}
    with tempfile.TemporaryDirectory(prefix="codex-tool-choice-") as cwd:
        await discover(args, cwd, controls)
        async with AppServer(args, cwd, controls) as app:
            async with asyncio.timeout(args.timeout):
                metadata = await preflight(app)
            emit({"ready": True, "metadata": metadata})
            if args.check:
                return
            for line in sys.stdin:
                if app.proc.returncode is not None:
                    emit({"tool_id": None, "elapsed_s": None, "cost_usd": None, "fatal": True,
                          "usage": {}, "error": "Adapter stopped after prior app-server failure; no retry"})
                else:
                    emit(await choose(app, line, wrapper, pricing))


if __name__ == "__main__":
    local = BENCHMARK.parent / "tools/codex/node_modules/.bin/codex"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=str(local) if local.exists() else shutil.which("codex") or "codex")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--timeout", type=float, default=180, help="Per-case and setup timeout in seconds")
    parser.add_argument("--check", action="store_true", help="Read-only preflight; zero model turns")
    options = parser.parse_args()
    if options.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        asyncio.run(main(options))
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        sys.exit(1)
