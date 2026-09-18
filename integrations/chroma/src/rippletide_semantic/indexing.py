"""Deterministic source chunking; Chroma supplies embeddings and vector search."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


EXTENSIONS = frozenset({
    ".py", ".md", ".txt", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".json", ".toml", ".yaml", ".yml", ".sql", ".sh",
})
IGNORED_DIRECTORIES = frozenset({
    "node_modules", "__pycache__", "dist", "build", "target", "venv", "env", "artifacts",
})
MAX_FILE_BYTES = 128 * 1024
MANAGED_BY = "rippletide-semantic-v1"


@dataclass(frozen=True)
class Chunk:
    id: str
    content: str
    metadata: dict[str, str | int]


def source_chunks(workspace: Path, *, lines_per_chunk: int = 32, overlap: int = 4) -> list[Chunk]:
    """Read local text source only; metadata line numbers are inclusive and one-based."""
    workspace = workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace must be a directory")
    if lines_per_chunk < 1 or not 0 <= overlap < lines_per_chunk:
        raise ValueError("chunk size must be positive and overlap smaller than chunk size")
    chunks = []
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if any(part.startswith(".") or part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != workspace):
            continue
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS or path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            continue
        lines = text.splitlines(keepends=True)
        digest = sha256(raw).hexdigest()
        for offset in range(0, len(lines), lines_per_chunk - overlap):
            end = min(offset + lines_per_chunk, len(lines))
            content = "".join(lines[offset:end])
            if not content.strip():
                continue
            chunk_id = sha256(f"{relative.as_posix()}:{offset + 1}:{end}:{digest}".encode()).hexdigest()
            chunks.append(Chunk(chunk_id, content, {
                "file": relative.as_posix(),
                "start_line": offset + 1,
                "end_line": end,
                "file_sha256": digest,
            }))
            if end == len(lines):
                break
    return chunks


def index_workspace(workspace: Path, data_dir: Path, collection_name: str) -> dict[str, Any]:
    """Refresh only this integration's collection, rejecting unrelated existing data."""
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    workspace = workspace.resolve(strict=True)
    data_dir = data_dir.resolve()
    if data_dir == workspace or workspace in data_dir.parents:
        raise ValueError("put the Chroma data directory outside the indexed workspace")
    chunks = source_chunks(workspace)
    if not chunks:
        return {"indexed": False, "ready": False, "reason": "NO_SOURCE_CHUNKS", "chunk_count": 0}
    client = chromadb.PersistentClient(path=str(data_dir), settings=Settings(anonymized_telemetry=False))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"managed_by": MANAGED_BY, "workspace": str(workspace)},
        configuration={"embedding_function": DefaultEmbeddingFunction()},
    )
    metadata = collection.metadata or {}
    if metadata.get("managed_by") != MANAGED_BY or metadata.get("workspace") != str(workspace):
        raise ValueError("collection belongs to another workspace or was not created by this integration")
    old_ids = set(collection.get(include=[])["ids"])
    for offset in range(0, len(chunks), 64):
        batch = chunks[offset:offset + 64]
        collection.upsert(
            ids=[chunk.id for chunk in batch],
            documents=[chunk.content for chunk in batch],
            metadatas=[chunk.metadata for chunk in batch],
        )
    stale_ids = sorted(old_ids - {chunk.id for chunk in chunks})
    if stale_ids:
        collection.delete(ids=stale_ids)
    return {
        "indexed": True,
        "chunk_count": collection.count(),
        "file_count": len({chunk.metadata["file"] for chunk in chunks}),
        "collection_name": collection_name,
        "workspace": str(workspace),
        "data_dir": str(data_dir),
        "embedding_function": "default",
        "embedding_model": "all-MiniLM-L6-v2 (local ONNX)",
    }
