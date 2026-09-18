from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def append_event(path: Path, run_id: str, event: str, **fields: Any) -> dict:
    record = {"schema_version": 1, "event": event, "timestamp": timestamp(), "run_id": run_id, **fields}
    payload = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode()
    # One append syscall: independent stdio servers never share a Python file buffer.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path}:{number}") from exc
    return result


def seed_database(path: Path, records: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to replace database: {path}")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE records (id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, metadata TEXT NOT NULL)")
        connection.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, project UNINDEXED, title, body)")
        for row in records:
            connection.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?)", (row["id"], row["project"], row["title"], row["body"], json.dumps(row)))
            connection.execute("INSERT INTO search VALUES (?, ?, ?, ?)", (row["id"], row["project"], row["title"], row["body"]))


class RecordStore:
    def __init__(self, path: Path):
        if not path.is_file():
            raise FileNotFoundError(f"Run database has not been prepared: {path}")
        self.path = path

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)

    def get(self, record_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT metadata FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown record ID: {record_id}")
        return json.loads(row[0])

    def search(self, query: str, project: str, limit: int = 5) -> list[dict]:
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        tokens = re.findall(r"[\w]+", query, re.UNICODE)[:24]
        if not tokens or not project.strip():
            raise ValueError("query and project must contain text")
        expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT records.metadata FROM search JOIN records ON records.id = search.id WHERE search MATCH ? AND records.project = ? ORDER BY bm25(search), records.id LIMIT ?",
                (expression, project, limit),
            ).fetchall()
        results = []
        for row in rows:
            item = json.loads(row[0])
            item["excerpt"] = item.pop("body")[:650]
            results.append(item)
        return results
