"""Reproducible extraction from immutable upstream sources, never executing them.

Run this module to print the source catalog for review. Normal tests/runs use the
bundled catalog offline. Whole benchmark datasets are not written to disk.
"""
from __future__ import annotations

import ast
import hashlib
import json
from urllib.request import urlopen

BFCL = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
TS = "c8571d7854316d2e1c5f288e59fe1e34e53f6dd1"
PREFIX = "berkeley-function-call-leaderboard/bfcl_eval/"


def json_schema(value):
    """Disclosed transport conversion, preserving source field descriptions."""
    if isinstance(value, list):
        return [json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: json_schema(item) for key, item in value.items()}
    if "type" in result:
        result["type"] = {"dict": "object", "tuple": "array", "float": "number"}.get(result["type"], result["type"])
    if result.get("type") == "object":
        result["additionalProperties"] = False
    return result


def annotation(node):
    if isinstance(node, ast.Name) and node.id in {"str", "float", "int", "bool"}:
        return {"type": {"str": "string", "float": "number", "int": "integer", "bool": "boolean"}[node.id]}
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Union":
        values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        return annotation(next(value for value in values if not (isinstance(value, ast.Name) and value.id == "NotGiven")))
    raise ValueError(f"Unsupported source annotation: {ast.dump(node)}")


def function_schema(node):
    properties, required = {}, []
    offset = len(node.args.args) - len(node.args.defaults)
    doc = ast.get_docstring(node) or ""
    for index, arg in enumerate(node.args.args):
        properties[arg.arg] = annotation(arg.annotation)
        for line in doc.splitlines():
            if line.strip().startswith(arg.arg + ":"):
                properties[arg.arg]["description"] = line.split(":", 1)[1].strip()
        if index < offset:
            required.append(arg.arg)
        else:
            default = node.args.defaults[index - offset]
            if isinstance(default, ast.Constant):
                properties[arg.arg]["default"] = default.value
    return {"name": node.name, "description": doc, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}


def extract(fetch=None) -> dict:
    provenance = {}

    def source(repo, revision, path):
        url = f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"
        data = fetch(url) if fetch else urlopen(url, timeout=30).read()
        provenance[url] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        return data.decode()

    bf = lambda path: source("ShishirPatil/gorilla", BFCL, PREFIX + path)
    ts = lambda path: source("apple-aiml-research/ToolSandbox", TS, "tool_sandbox/" + path)
    cases = {}
    for case, category, identifier in (("B01", "multiple", "multiple_5"), ("B02", "irrelevance", "irrelevance_55"), ("B03", "parallel_multiple", "parallel_multiple_32")):
        path = f"data/BFCL_v4_{category}.json"
        rows = [json.loads(line) for line in bf(path).splitlines() if line.strip()]
        row = next(row for row in rows if row["id"] == identifier)
        answer = []
        if case != "B02":
            answer_path = f"data/possible_answer/BFCL_v4_{category}.json"
            answer = next(json.loads(line)["ground_truth"] for line in bf(answer_path).splitlines() if json.loads(line)["id"] == identifier)
        cases[case] = {"benchmark": "BFCL", "revision": BFCL, "entry_id": identifier,
                       "source_path": PREFIX + path, "prompt": row["question"][0][0]["content"],
                       "tools": [{**tool, "parameters": json_schema(tool["parameters"])} for tool in row["function"]],
                       "oracle": {"reference_calls": answer}, "source_entry_sha256": hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()}
    # Irrelevance has a category-level no-call rule, not a possible_answer row.
    bf("eval_checker/eval_runner.py")
    scenario_source = ts("scenarios/multiple_tool_call_scenarios.py")
    tree = ast.parse(scenario_source)
    functions = {}
    for filename in ("utilities", "reminder", "contact", "setting", "messaging"):
        for node in ast.parse(ts(f"tools/{filename}.py")).body:
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = node
    ts("scenarios/base_scenarios.py")
    ts("common/evaluation.py")
    ts("common/scenario.py")
    for case, identifier in (("B04", "search_reminder_with_recency_upcoming"), ("B05", "send_message_with_contact_content_cellular_off")):
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and node.func.id == "ScenarioExtension" and
                    any(k.arg == "name" and isinstance(k.value, ast.Constant) and k.value.value == identifier for k in node.keywords))
        fields = {k.arg: k.value for k in node.keywords}
        messages = fields["messages"].elts
        public = next(message for message in messages if any(isinstance(key, ast.Constant) and key.value == "sender" and isinstance(value, ast.Attribute) and value.attr == "USER" for key, value in zip(message.keys, message.values)))
        prompt = ast.literal_eval(next(value for key, value in zip(public.keys, public.values) if key.value == "content"))
        tools = [function_schema(functions[name]) for name in ast.literal_eval(fields["tool_allow_list"])]
        cases[case] = {"benchmark": "ToolSandbox", "revision": TS, "entry_id": identifier,
                       "source_path": "tool_sandbox/scenarios/multiple_tool_call_scenarios.py", "prompt": prompt,
                       "tools": tools, "oracle": {"mode": "local_milestone_contract", "upstream_score": None},
                       "source_entry_sha256": hashlib.sha256(ast.dump(node).encode()).hexdigest()}
    licenses = {"BFCL": source("ShishirPatil/gorilla", BFCL, "LICENSE"),
                "ToolSandbox": source("apple-aiml-research/ToolSandbox", TS, "LICENSE")}
    return {"schema_version": 1, "sources": provenance, "licenses": licenses, "cases": cases,
            "adaptations": ["dict→object, tuple→array, float→number JSON transport; BFCL function dots mapped to double underscores",
                            "Synthetic weather values; fixed UTC clock; reduced synthetic reminder/contact state",
                            "Local executable reference/milestone checks; official upstream scorers not executed",
                            "No source Python is evaluated or executed; no hidden user-simulator messages are exposed"]}


if __name__ == "__main__":
    print(json.dumps(extract(), ensure_ascii=False, indent=2))
