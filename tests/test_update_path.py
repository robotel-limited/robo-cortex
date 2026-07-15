import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.errors import NotFoundError, ValidationError
from robo_cortex.core.invalidate import refresh_staleness, update_path
from robo_cortex.core.memory import get_memory, record_memory

from .fixtures import build_fixture_repo_a, run_git


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_update_path_recovers_rename_and_edit(tmp_path):
    """The exact-hash auto-relink (Stage 6) can't handle a file renamed
    *and* edited in the same commit -- that's this command's job."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )

    run_git(repo, "mv", "src/fixture_a/scanner.py", "src/fixture_a/batch_scanner.py")
    (repo / "src" / "fixture_a" / "batch_scanner.py").write_text(
        "def scan_batch(items, batch_size=999): return items\n"
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "rename and edit scanner")

    refresh_staleness(conn, repo)
    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"
    assert "path_missing:src/fixture_a/scanner.py" in memory["status_reason"]

    updated = update_path(conn, repo, result["id"], "src/fixture_a/scanner.py", "src/fixture_a/batch_scanner.py")

    assert updated["paths"] == [{
        "path": "src/fixture_a/batch_scanner.py",
        "blob_hash": updated["paths"][0]["blob_hash"],
    }]
    # heals immediately since this was its only problem -- back to whatever
    # it was before the flag (provisional here, since it was never promoted)
    assert updated["status"] == "provisional"
    assert updated["status_reason"] is None


def test_update_path_rejects_dead_new_path(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="x", paths=["src/fixture_a/scanner.py"],
    )
    with pytest.raises(ValidationError, match="does not exist at HEAD"):
        update_path(conn, repo, result["id"], "src/fixture_a/scanner.py", "no/such/file.py")


def test_update_path_rejects_unknown_old_path(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="x", paths=["src/fixture_a/scanner.py"],
    )
    with pytest.raises(NotFoundError):
        update_path(conn, repo, result["id"], "src/fixture_a/not_linked.py", "src/fixture_a/exporter.py")
