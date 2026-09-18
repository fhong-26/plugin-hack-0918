"""Select an actual session tool; the caller retains argument generation/execution."""

import math

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rippletide.identity import ROUTE_TIMEOUT_SECONDS


class Tool(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    context: str
    question: str = Field(min_length=1)
    tools: list[Tool] = Field(min_length=1)


def select_tool(worker, **parameters) -> dict:
    """Every valid request reaches the local model, including single-tool catalogs.

    The host supplies its complete callable catalog. This layer neither discovers
    nor filters tools, and never substitutes an LLM/rule decision on failure.
    """
    try:
        request = SelectionRequest.model_validate(parameters)
        names = [tool.name for tool in request.tools]
        if len(set(names)) != len(names) or not request.question.strip():
            raise ValueError("Tool names must be unique and the question nonempty")
    except (ValidationError, ValueError):
        return {"status": "error", "reason_code": "INVALID_REQUEST"}

    try:
        result = worker.predict({
            "goal": request.question,
            "context": request.context,
            "candidates": [{"id": tool.name, "description": tool.description}
                           for tool in request.tools],
        }, timeout=ROUTE_TIMEOUT_SECONDS)
    except Exception:
        return {"status": "error", "reason_code": "MODEL_ERROR"}
    if not isinstance(result, dict):
        return {"status": "error", "reason_code": "INVALID_MODEL_OUTPUT"}
    if result.get("status") != "selected":
        return {"status": "error", "reason_code": result.get("reason_code", "MODEL_ERROR")}
    score = result.get("score")
    if (result.get("route_id") not in names or isinstance(score, bool)
            or not isinstance(score, (float, int)) or not math.isfinite(score) or not 0 <= score <= 1):
        return {"status": "error", "reason_code": "INVALID_MODEL_OUTPUT"}
    return {"status": "selected", "tool": result["route_id"], "score": score}
