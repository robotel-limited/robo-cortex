import subprocess
from datetime import datetime, timedelta, timezone

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.invalidate import refresh_staleness
from robo_cortex.core.memory import get_memory, record_memory

from .fixtures import build_fixture_repo_a, run_git


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def _commit(repo, message="update"):
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)


def run_git_capture(repo, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_edit_flags_needs_review_with_correct_reason(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )

    (repo / "src" / "fixture_a" / "scanner.py").write_text(
        "def scan_batch(items, batch_size=999):\n    return items\n"
    )
    _commit(repo, "change batch size")

    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"
    assert memory["status_reason"] == "path_changed:src/fixture_a/scanner.py"


def test_revert_heals_back_to_previous_status(tmp_path):
    repo, conn = _store(tmp_path)
    original = (repo / "src" / "fixture_a" / "scanner.py").read_text()
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    _commit(repo, "break it")
    refresh_staleness(conn, repo)
    assert get_memory(conn, result["id"])["status"] == "needs_review"

    (repo / "src" / "fixture_a" / "scanner.py").write_text(original)
    _commit(repo, "revert")
    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "active"
    assert memory["status_reason"] is None


def test_file_deleted_degrades_to_path_missing(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )

    (repo / "src" / "fixture_a" / "exporter.py").unlink()
    _commit(repo, "delete exporter")
    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"
    assert memory["status_reason"] == (
        "path_missing:src/fixture_a/exporter.py — recover with: "
        "git log --follow --diff-filter=R -- src/fixture_a/exporter.py"
    )


def test_untouched_memories_are_never_flagged(tmp_path):
    repo, conn = _store(tmp_path)
    untouched = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The health check endpoint returns ok.",
        paths=["src/fixture_a/api/routes.py"],
    )
    edited = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    _commit(repo, "edit scanner only")
    refresh_staleness(conn, repo)

    assert get_memory(conn, untouched["id"])["status"] == "provisional"
    assert get_memory(conn, edited["id"])["status"] == "needs_review"


def test_git_mv_with_unchanged_content_relinks_not_missing(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )

    run_git(repo, "mv", "src/fixture_a/scanner.py", "src/fixture_a/batch_scanner.py")
    _commit(repo, "rename scanner")
    changes = refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "provisional"  # unaffected -- content never changed
    assert memory["status_reason"] is None
    assert memory["paths"] == [
        {"path": "src/fixture_a/batch_scanner.py", "blob_hash": result["paths"][0]["blob_hash"]}
    ]
    assert {"memory_id": result["id"], "type": "relinked",
            "old_path": "src/fixture_a/scanner.py",
            "new_path": "src/fixture_a/batch_scanner.py"} in changes


def test_genuinely_deleted_file_still_degrades_to_path_missing_after_other_renames(tmp_path):
    """A delete must not be mistaken for a rename just because *some* file
    in the repo happens to share a hash with something else."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )

    (repo / "src" / "fixture_a" / "exporter.py").unlink()
    _commit(repo, "delete exporter, no replacement with matching content")
    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"
    assert memory["status_reason"] == (
        "path_missing:src/fixture_a/exporter.py — recover with: "
        "git log --follow --diff-filter=R -- src/fixture_a/exporter.py"
    )


def test_pathless_memory_flags_stale_after_age_threshold(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="lesson", scope="repo", confidence="medium",
        statement="Prefer SQLite for this kind of local-first tool.",
    )
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=200)).strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z"
    )
    conn.execute(
        "UPDATE memory SET last_verified_at = ? WHERE id = ?", (old_timestamp, result["id"])
    )

    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"
    assert memory["status_reason"].startswith("stale_unverified:")


def test_pathless_memory_within_threshold_is_not_flagged(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="lesson", scope="repo", confidence="medium",
        statement="Prefer SQLite for this kind of local-first tool.",
    )

    refresh_staleness(conn, repo)

    assert get_memory(conn, result["id"])["status"] == "provisional"


def test_terminal_statuses_are_never_touched(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    conn.execute("UPDATE memory SET status = 'superseded' WHERE id = ?", (result["id"],))

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    _commit(repo, "edit after supersede")
    refresh_staleness(conn, repo)

    assert get_memory(conn, result["id"])["status"] == "superseded"


def test_affected_handles_dashed_filenames(tmp_path):
    from robo_cortex.core.invalidate import affected

    repo, conn = _store(tmp_path)

    (repo / "-x.py").write_text("x=1\n")
    _commit(repo, "add dashed file")

    result = record_memory(
        conn, repo, type="lesson", scope="repo", confidence="low",
        statement="Dashed file lesson.",
        paths=["-x.py"],
    )

    (repo / "-x.py").write_text("x=2\n")

    affected_result = affected(conn, repo)

    assert affected_result["matched"] == 1
    assert affected_result["data"][0]["id"] == result["id"]


def test_comment_only_python_edit_does_not_flag(tmp_path):
    """EVALUATION.md §8 Test 1: a comment-only addition to exporter.py
    spuriously flipped all 4 linked memories to needs_review. This is the
    fix: the token-equivalence check recognizes the edit as cosmetic and
    silently reanchors instead of flagging.
    """
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="high",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    exporter = repo / "src" / "fixture_a" / "exporter.py"
    exporter.write_text(
        'def export_csv(rows, delimiter=";"):\n'
        "    # join rows using the configured delimiter\n"
        "    return delimiter.join(rows)\n"
    )
    _commit(repo, "add explanatory comment")

    changes = refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "active"
    assert memory["status_reason"] is None
    assert any(c["type"] == "reanchored" for c in changes)


def test_whitespace_only_python_edit_does_not_flag(tmp_path):
    """EVALUATION.md §8 Test 2: a single trailing blank line flipped the
    linked memory to needs_review. Same fix, whitespace-only case."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    scanner = repo / "src" / "fixture_a" / "scanner.py"
    scanner.write_text(scanner.read_text() + "\n")
    _commit(repo, "trailing blank line")

    changes = refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "active"
    assert memory["status_reason"] is None
    assert any(c["type"] == "reanchored" for c in changes)


def test_reanchor_updates_stored_blob_hash(tmp_path):
    """After a cosmetic reanchor, the stored hash must track the new blob --
    otherwise the next refresh would recompute the same (now stale) diff
    and have to re-derive equivalence forever."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="high",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    exporter = repo / "src" / "fixture_a" / "exporter.py"
    exporter.write_text(
        'def export_csv(rows, delimiter=";"):\n'
        "    # a comment\n"
        "    return delimiter.join(rows)\n"
    )
    _commit(repo, "add comment")
    refresh_staleness(conn, repo)

    stored_hash = conn.execute(
        "SELECT blob_hash FROM memory_path WHERE memory_id = ?", (result["id"],)
    ).fetchone()[0]
    current_hash = run_git_capture(repo, "rev-parse", "HEAD:src/fixture_a/exporter.py")
    assert stored_hash == current_hash


def test_semantic_variable_rename_still_flags(tmp_path):
    """A rename changes the token stream (a NAME token's string differs),
    so it must still be flagged -- the equivalence check is not a rubber
    stamp for "any edit to a .py file"."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="high",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    exporter = repo / "src" / "fixture_a" / "exporter.py"
    exporter.write_text(
        'def export_csv(items, delimiter=";"):\n'
        "    return delimiter.join(items)\n"
    )
    _commit(repo, "rename rows to items")

    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"


def test_indentation_change_still_flags(tmp_path):
    """ARCHITECTURE.md's own rationale for rejecting `git diff -w`:
    indentation is semantic in Python, so a width change must still flag,
    even though it's "just whitespace" in a textual sense."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="high",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    exporter = repo / "src" / "fixture_a" / "exporter.py"
    exporter.write_text(
        'def export_csv(rows, delimiter=";"):\n'
        "        return delimiter.join(rows)\n"
    )
    _commit(repo, "widen indentation")

    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"


def test_non_python_file_change_still_flags(tmp_path):
    """The equivalence check only applies to .py paths -- a non-Python file
    (e.g. a markdown doc) keeps today's exact-hash behavior unchanged."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="ADR 0001 explains the SQLite choice.",
        paths=["docs/adr-0001-storage.md"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    adr = repo / "docs" / "adr-0001-storage.md"
    adr.write_text(adr.read_text() + "\n")
    _commit(repo, "trailing blank line in doc")

    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"


def test_syntax_error_falls_back_to_flagging(tmp_path):
    """A tokenization failure (here: invalid syntax in the new content)
    must degrade to "cannot prove equivalence," not crash and not silently
    treat the memory as unchanged."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="high",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))

    exporter = repo / "src" / "fixture_a" / "exporter.py"
    exporter.write_text("def export_csv(rows, delimiter=(:\n")
    _commit(repo, "introduce a syntax error")

    refresh_staleness(conn, repo)

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "needs_review"


def test_refresh_staleness_caches_head_sha(tmp_path):
    from robo_cortex.core.invalidate import refresh_staleness
    from unittest.mock import patch

    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="lesson", scope="repo", confidence="low",
        statement="Test cache.",
        paths=["src/fixture_a/scanner.py"],
    )

    with patch("robo_cortex.core.invalidate.head_tree") as mock_tree:
        mock_tree.return_value = (
            {"src/fixture_a/scanner.py": "fakehash"},
            {"fakehash": ["src/fixture_a/scanner.py"]},
        )

        refresh_staleness(conn, repo)
        first_call_count = mock_tree.call_count

        refresh_staleness(conn, repo)
        second_call_count = mock_tree.call_count

    assert first_call_count == second_call_count, "head_tree should not be called again (cached)"
