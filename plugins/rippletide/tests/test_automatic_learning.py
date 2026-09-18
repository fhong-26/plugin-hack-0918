import asyncio
from types import SimpleNamespace
import threading

import pytest

from rippletide import learning
from rippletide.personalization import init_profile, atomic_json


class Worker:
    def __init__(self):
        self._request_lock = threading.Lock()
        self.maintenance = False
        self.closed = self.started = 0
    def close(self):
        self.closed += 1
    def start(self, **kwargs):
        self.started += 1


@pytest.mark.parametrize("consent", [False, True])
def test_background_scheduler_requires_prior_opt_in_and_deduplicates(tmp_path, monkeypatch, consent):
    init_profile(tmp_path, user_id="a", preferences=[], learn=consent, auto_train=consent)
    atomic_json(tmp_path / "feedback.json", [{"decision_id": str(i)} for i in range(40)])
    monkeypatch.setenv("RIPPLETIDE_PROFILE", str(tmp_path))
    worker = Worker()
    calls = []
    ticks = 0
    async def sleep(_):
        nonlocal ticks
        ticks += 1
        if ticks > 2:
            raise asyncio.CancelledError
    class Process:
        returncode = 0
        async def wait(self):
            return 0
    async def launch(*args, **kwargs):
        assert worker.maintenance and worker.closed == 1
        calls.append(args)
        return Process()
    monkeypatch.setattr(learning.asyncio, "sleep", sleep)
    monkeypatch.setattr(learning.asyncio, "create_subprocess_exec", launch)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(learning.automatic_learning(SimpleNamespace(worker=worker, model="qwen3-0.6b-torch")))
    assert len(calls) == int(consent)
    assert worker.started == int(consent)
    assert not worker.maintenance


def test_shutdown_terminates_the_training_child_without_restarting_inference(tmp_path, monkeypatch):
    init_profile(tmp_path, user_id="a", preferences=[], learn=True, auto_train=True, mode="lora")
    atomic_json(tmp_path / "feedback.json", [{"decision_id": str(i)} for i in range(40)])
    monkeypatch.setenv("RIPPLETIDE_PROFILE", str(tmp_path))
    worker = Worker()
    async def scenario():
        entered = asyncio.Event()
        released = asyncio.Event()
        class Process:
            returncode = None
            terminated = False
            async def wait(self):
                entered.set()
                await released.wait()
                return self.returncode
            def terminate(self):
                self.terminated = True
                self.returncode = -15
                released.set()
        process = Process()
        async def launch(*args, **kwargs):
            assert args[-1] == "lora"
            return process
        async def sleep(_):
            return None
        monkeypatch.setattr(learning.asyncio, "sleep", sleep)
        monkeypatch.setattr(learning.asyncio, "create_subprocess_exec", launch)
        task = asyncio.create_task(learning.automatic_learning(SimpleNamespace(worker=worker, model="qwen3-0.6b-torch")))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.terminated
    asyncio.run(scenario())
    assert worker.closed == 1 and worker.started == 0 and not worker.maintenance
