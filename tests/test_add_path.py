import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.errors import NotFoundError, ValidationError
from robo_cortex.core.invalidate import add_path, refresh_staleness
from robo_cortex.core.memory import get_memory, record_memory

from .fixtures import build_fixture_repo_a, run_git


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_add_path_attaches_new_path(tmp_path):
    """The gap `update_path` doesn't cover: attaching a path to a memory
    that had none, after the fact (e.g. once the file it describes has
    finally been committed)."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
    )
    assert result["paths"] == []

    updated = add_path(conn, repo, result["id"], "src/fixture_a/scanner.py")

    assert updated["paths"] == [{
        "path": "src/fixture_a/scanner.py",
        "blob_hash": updated["paths"][0]["blob_hash"],
    }]
    assert updated["paths"][0]["blob_hash"] != ""


def test_add_path_rejects_dead_path(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low", statement="x",
    )
    with pytest.raises(ValidationError, match="does not exist at HEAD"):
        add_path(conn, repo, result["id"], "no/such/file.py")


def test_add_path_rejects_duplicate_path(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="x", paths=["src/fixture_a/scanner.py"],
    )
    with pytest.raises(ValidationError, match="already linked"):
        add_path(conn, repo, result["id"], "src/fixture_a/scanner.py")


def test_add_path_rejects_unknown_memory(tmp_path):
    repo, conn = _store(tmp_path)
    with pytest.raises(NotFoundError):
        add_path(conn, repo, 999, "src/fixture_a/scanner.py")


def test_add_path_rejects_global_scope(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="lesson", scope="global", confidence="high",
        statement="x", assumptions="some condition",
    )
    with pytest.raises(ValidationError, match="cannot have linked paths"):
        add_path(conn, repo, result["id"], "src/fixture_a/scanner.py")


def test_add_path_feeds_into_staleness_mechanism(tmp_path):
    """End-to-end proof that a path attached via add_path is a real,
    tracked link -- not a cosmetic no-op -- by driving it through the same
    staleness cycle a --path-at-record-time link would go through."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
    )

    updated = add_path(conn, repo, result["id"], "src/fixture_a/scanner.py")
    assert updated["status"] == "provisional"

    (repo / "src" / "fixture_a" / "scanner.py").write_text(
        "def scan_batch(items, batch_size=999): return items\n"
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "change batch size")

    refresh_staleness(conn, repo)
    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"
    assert "path_changed:src/fixture_a/scanner.py" in memory["status_reason"]
