"""Experimental CPU server: warm the worker before advertising MCP readiness."""
import os
from rippletide.router import Router
from rippletide.server import create_server

if not os.environ.get("RIPPLETIDE_RUN_DIR"):
    raise RuntimeError("This launcher is restricted to an explicit experiment")
router = Router(model="qwen3-0.6b-torch", timeout_seconds=120)
router.worker.start(wait=True)
create_server(router).run(transport="stdio")
