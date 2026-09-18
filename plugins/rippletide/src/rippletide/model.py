"""Persistent worker lifecycle, including bounded request waits and crash recovery."""

import json
import os
import queue
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

from rippletide.artifacts import read_artifacts, supported_platform
from rippletide.catalog import model_spec
from rippletide.identity import model_identity


class WorkerManager:
    def __init__(self, data_dir: Path, model: str | None = None):
        self.data_dir = data_dir
        self.model = model_spec(model).alias
        self._identity = model_identity(self.model)
        self._process = None
        self._state = "stopped"
        self._error = None
        self._startup_ms = None
        self._lifecycle_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._ready = threading.Event()
        self._responses = queue.Queue()
        self.maintenance = False
        self._profile_stamp = None

    @staticmethod
    def profile_stamp():
        from rippletide.personalization import default_profile_path
        root = default_profile_path()
        return tuple((name, (root / name).stat().st_mtime_ns, (root / name).stat().st_size)
                     for name in ("profile.json", "feedback.json", "active.json") if (root / name).is_file())

    def status(self) -> dict:
        process = self._process
        return {
            "state": self._state, "ready": self._state == "ready" and process is not None and process.poll() is None,
            "pid": process.pid if process is not None and process.poll() is None else None,
            "startup_ms": self._startup_ms, "error": self._error,
            "model_identity": self._identity,
        }

    def start(self, *, wait: bool = False, timeout: float = 180) -> bool:
        if self.maintenance:
            return False
        with self._lifecycle_lock:
            if self._process is not None and self._process.poll() is None:
                pass
            else:
                try:
                    if not supported_platform() and model_spec(self.model).adapter != "torch-direct-logit":
                        raise RuntimeError("Apple Silicon macOS with MLX is required")
                    read_artifacts(self.data_dir, model=self.model)
                    self._ready = threading.Event()
                    self._responses = queue.Queue()
                    self._error = None
                    self._state = "loading"
                    self._process = subprocess.Popen(
                        [sys.executable, "-X", "utf8", "-u", "-m", "rippletide.worker", "--data-dir", str(self.data_dir), "--model", self.model],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                        text=True, encoding="utf-8", bufsize=1,
                    )
                    self._profile_stamp = self.profile_stamp()
                    threading.Thread(target=self._read_worker, args=(self._process, self._responses, self._ready), daemon=True).start()
                except (OSError, ValueError, KeyError, RuntimeError) as exc:
                    self._state, self._error = "unavailable", str(exc)
                    return False
        if wait:
            if not self._ready.wait(timeout):
                self._stop("startup_timeout", "Model startup deadline exceeded")
        return self.status()["ready"]

    def _read_worker(self, process, responses, ready):
        try:
            for line in process.stdout:
                message = json.loads(line)
                if process is not self._process:
                    return
                if message.get("type") == "ready":
                    identity = message.get("model_identity")
                    if identity != self._identity:
                        raise ValueError("Loaded worker model identity does not match configured model")
                    self._startup_ms = message["startup_ms"]
                    self._state = "ready"
                    ready.set()
                elif message.get("type") == "startup_error":
                    self._error = message["error"]
                    self._state = "failed"
                    ready.set()
                elif message.get("type") == "result":
                    responses.put(message["result"])
                else:
                    raise ValueError("Unexpected worker protocol message")
        except (ValueError, OSError) as exc:
            if process is self._process:
                self._stop("failed", f"Worker protocol error: {exc}")
        finally:
            if process is self._process and self._state not in {"stopped", "timed_out", "startup_timeout"}:
                self._state = "failed"
                self._error = self._error or "Model worker exited"
            ready.set()
            responses.put({"status": "defer", "reason_code": "MODEL_CRASH"})
            process.stdout.close()

    def _stop(self, state: str, error: str | None = None):
        with self._lifecycle_lock:
            process, self._process = self._process, None
            self._state, self._error = state, error
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                # Cleanup cannot extend an inference request's deadline.
                threading.Thread(target=self._reap, args=(process,), daemon=True).start()

    @staticmethod
    def _reap(process):
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdin:
            process.stdin.close()

    @staticmethod
    def _write_packet(process, packet: dict, deadline: float):
        payload = memoryview((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
        descriptor = process.stdin.fileno()
        if os.name == "nt":
            # Windows select() cannot wait on anonymous pipes. The writer owns
            # only this child pipe; killing a timed-out child releases the write.
            completed = queue.Queue(maxsize=1)
            def write():
                try:
                    remaining = payload
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if not written:
                            raise BrokenPipeError("Worker input closed")
                        remaining = remaining[written:]
                    completed.put(None)
                except (OSError, ValueError) as exc:
                    completed.put(exc)
            threading.Thread(target=write, daemon=True).start()
            try:
                error = completed.get(timeout=max(0, deadline - time.perf_counter()))
            except queue.Empty:
                raise TimeoutError("Worker input deadline exceeded") from None
            if error:
                raise error
            return
        os.set_blocking(descriptor, False)
        while payload:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError("Worker input deadline exceeded")
            _, writable, _ = select.select([], [descriptor], [], remaining)
            if not writable:
                raise TimeoutError("Worker input deadline exceeded")
            try:
                written = os.write(descriptor, payload)
            except BlockingIOError:
                continue
            if written == 0:
                raise BrokenPipeError("Worker input closed")
            payload = payload[written:]

    def predict(self, packet: dict, timeout: float) -> dict:
        deadline = time.perf_counter() + timeout
        if timeout <= 0 or not self._request_lock.acquire(timeout=max(0, timeout)):
            return {"status": "defer", "reason_code": "ROUTER_TIMEOUT"}
        try:
            if self._profile_stamp is not None and self._profile_stamp != self.profile_stamp():
                self._stop("stopped", "Reloading an explicitly updated user profile")
            if not self.status()["ready"]:
                self.start()
                return {"status": "defer", "reason_code": "MODEL_NOT_READY", "worker_state": self._state}
            process = self._process
            try:
                # A ready worker can stop reading. Bound the write itself, not
                # just the wait for a response after the pipe has been filled.
                self._write_packet(process, packet, deadline)
                result = self._responses.get(timeout=max(0, deadline - time.perf_counter()))
                return {**result, "worker_pid": process.pid}
            except (queue.Empty, TimeoutError):
                self._stop("timed_out", "Routing exceeded its two-second deadline")
                return {"status": "defer", "reason_code": "ROUTER_TIMEOUT"}
            except (BrokenPipeError, OSError, AttributeError):
                self._stop("failed", "Model worker connection closed")
                return {"status": "defer", "reason_code": "MODEL_CRASH"}
        finally:
            self._request_lock.release()

    def close(self):
        self._stop("stopped")
