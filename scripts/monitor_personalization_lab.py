"""Observe an explicitly identified local experiment process, without secrets."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import psutil

parser = argparse.ArgumentParser()
parser.add_argument("--pid", type=int, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
process = psutil.Process(args.pid)
command = process.cmdline()
if "run" not in command or not any(Path(arg).name == "personalization_lab.py" for arg in command):
    raise ValueError("Refusing to monitor a process other than the routing experiment")
args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("x", encoding="utf-8") as stream:
    while process.is_running():
        try:
            memory = process.memory_info()
            sample = {"timestamp": datetime.now(timezone.utc).isoformat(), "pid": process.pid,
                "rss_bytes": memory.rss, "peak_rss_bytes": getattr(memory, "peak_wset", None),
                "cpu_percent": process.cpu_percent(), "cpu_seconds": sum(process.cpu_times()[:2]),
                "system_available_bytes": psutil.virtual_memory().available}
            stream.write(json.dumps(sample) + "\n")
            stream.flush()
        except psutil.NoSuchProcess:
            break
        time.sleep(10)
