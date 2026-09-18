from hashlib import sha256

import pytest

from rippletide_semantic.indexing import index_workspace, source_chunks


def test_source_locations_and_repeatable_ids(tmp_path):
    source = "".join(f"line {number}\n" for number in range(1, 10))
    (tmp_path / "app.py").write_text(source)
    chunks = source_chunks(tmp_path, lines_per_chunk=4, overlap=1)
    assert [(c.metadata["start_line"], c.metadata["end_line"]) for c in chunks] == [(1, 4), (4, 7), (7, 9)]
    assert chunks[1].content == "line 4\nline 5\nline 6\nline 7\n"
    assert chunks[1].metadata["file"] == "app.py"
    assert chunks == source_chunks(tmp_path, lines_per_chunk=4, overlap=1)
    (tmp_path / "app.py").write_text(source.replace("line 5", "updated"))
    assert source_chunks(tmp_path, lines_per_chunk=4, overlap=1)[1].id != chunks[1].id


def test_ignores_hidden_binary_and_external_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('visible')\n")
    (workspace / ".codex").mkdir()
    (workspace / ".codex" / "agents.md").write_text("not source")
    (workspace / "binary.txt").write_bytes(b"hello\x00world")
    (workspace / "invalid.txt").write_bytes(b"\xff")
    outside = tmp_path / "grader.py"
    outside.write_text("private answer")
    (workspace / "external.py").symlink_to(outside)
    assert [c.metadata["file"] for c in source_chunks(workspace)] == ["app.py"]


def test_invalid_overlap_rejected(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        source_chunks(tmp_path, lines_per_chunk=4, overlap=4)


def test_empty_workspace_cannot_claim_semantic_readiness(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = index_workspace(workspace, tmp_path / "chroma", "empty_sources")
    assert result == {"indexed": False, "ready": False, "reason": "NO_SOURCE_CHUNKS", "chunk_count": 0}
    assert not (tmp_path / "chroma").exists()


def test_metadata_hash_and_contents_preserve_source_bytes(tmp_path):
    raw = b"first\r\nsecond\r\n"
    (tmp_path / "windows.txt").write_bytes(raw)
    chunk = source_chunks(tmp_path)[0]
    assert chunk.content.encode() == raw
    assert chunk.metadata["file_sha256"] == sha256(raw).hexdigest()
