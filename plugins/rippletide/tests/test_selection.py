from types import SimpleNamespace

import pytest

from rippletide.direct_logit import prepare_input
from rippletide.labels import label_ids
from rippletide.selection import select_tool


def test_complete_catalog_and_context_reach_model_without_preselection():
    tools = [{"name": f"tool_{i}", "description": f"Operation {i}"} for i in range(40)]
    calls = []

    def predict(packet, timeout):
        calls.append(packet)
        return {"status": "selected", "route_id": "tool_39", "score": 0.9}

    result = select_tool(SimpleNamespace(predict=predict), context="History and current user request",
                         question="What should run next?", tools=tools)
    assert result == {"status": "selected", "tool": "tool_39", "score": 0.9}
    assert calls == [{"context": "History and current user request", "goal": "What should run next?",
                      "candidates": [{"id": tool["name"], "description": tool["description"]} for tool in tools]}]


@pytest.mark.parametrize("reply", [
    {"status": "defer", "reason_code": "MODEL_NOT_READY"},
    {"status": "selected", "route_id": "invented", "score": 0.9},
    {"status": "selected", "route_id": "exec_command", "score": float("nan")},
    {"status": "selected", "route_id": "exec_command", "score": True},
    None,
])
def test_single_tool_still_uses_model_and_errors_never_authorize_fallback(reply):
    calls = []
    worker = SimpleNamespace(predict=lambda *args, **kwargs: calls.append(args) or reply)
    result = select_tool(worker, context="Read file", question="Which tool?",
                         tools=[{"name": "exec_command", "description": "Run a shell command"}])
    assert len(calls) == 1
    assert result["status"] == "error" and "tool" not in result


def test_duplicate_tool_names_are_rejected_before_inference():
    tool = {"name": "exec_command", "description": "Run a command"}
    assert select_tool(None, context="", question="Which tool?", tools=[tool, tool]) == {
        "status": "error", "reason_code": "INVALID_REQUEST"}


def test_more_than_25_labels_are_distinct_and_every_candidate_is_in_prompt():
    class Tokenizer:
        def get_vocab(self):
            return {chr(i): i for i in range(48, 123)}

        def encode(self, text, **_):
            return [ord(char) for char in text]

        def decode(self, ids):
            return "".join(map(chr, ids))

        def apply_chat_template(self, messages, **_):
            content = messages[-1]["content"]
            assert all(f"tool_{i}" in content for i in range(40))
            assert "preserve me " * 200 in content
            return self.encode(content)

    tokenizer = Tokenizer()
    labels = label_ids(tokenizer, 40)
    assert len(labels) == len(set(labels.values())) == 40
    packet = {"goal": "Which tool?", "context": "preserve me " * 200,
              "candidates": [{"id": f"tool_{i}", "description": "A tool"} for i in range(40)]}
    tokens, observations = prepare_input(tokenizer, packet, labels, 8192)
    assert 1024 < len(tokens) < 8192 and observations == []


@pytest.mark.model
def test_pinned_model_selects_from_large_session_catalog():
    from rippletide.identity import data_directory
    from rippletide.model import WorkerManager

    worker = WorkerManager(data_directory())
    tools = [{"name": f"tool_{i}", "description": f"Read document {i}."} for i in range(35)]
    try:
        assert worker.start(wait=True), worker.status()
        result = select_tool(worker, context="The user needs information in document 34.",
                             question="Which tool should run next?", tools=tools)
        assert result["status"] == "selected", result
        assert result["tool"] in {tool["name"] for tool in tools}
        # This is a capacity/readout test, not an accuracy benchmark.
        assert 0 <= result["score"] <= 1
    finally:
        worker.close()
