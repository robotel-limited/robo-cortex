"""Regression tests for the re-verification loop bug found in live review
of Stage 7 (commit 145c662): `change_status(..., "active", ...)` cleared
the status column but never recaptured linked-path blob hashes or bumped
`last_verified_at`, so a memory manually cleared out of `needs_review`
re-tripped the very next staleness check. ARCHITECTURE.md §5.3 promises
hash capture "at record and at verify" -- the "at verify" half never
existed. Fixed via `memory.reverify()`, called from both `change_status`
(-> active) and `attach_evidence`'s provisional->active promotion.
"""

from datetime import datetime, timedelta, timezone

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.lifecycle import change_status
from robo_cortex.core.invalidate import refresh_staleness
from robo_cortex.core.memory import get_memory, record_memory

from .fixtures import build_fixture_repo_a, run_git


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_activate_breaks_the_reflag_loop_for_edited_path(tmp_path):
    """The exact scenario from live review: record -> edit+commit -> flag
    -> activate -> the memory must NOT immediately re-flag on the next check."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (result["id"],))
    original_hash = result["paths"][0]["blob_hash"]

    (repo / "src" / "fixture_a" / "scanner.py").write_text(
        "def scan_batch(items, batch_size=999): return items\n"
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "bump batch size")

    refresh_staleness(conn, repo)
    assert get_memory(conn, result["id"])["status"] == "needs_review"

    change_status(conn, repo, result["id"], "active", "reviewed, still accurate as documented")

    # the bug: blob_hash was never recaptured, so this immediately re-flagged
    refresh_staleness(conn, repo)
    memory = get_memory(conn, result["id"])
    assert memory["status"] == "active"
    # status_reason legitimately holds the manual activation's own reason
    # (unlike the automatic heal path, which clears it) -- what matters here
    # is that refresh_staleness did NOT overwrite it back to a path_changed
    # reason, i.e. it did not re-flag.
    assert memory["status_reason"] == "reviewed, still accurate as documented"

    new_hash = memory["paths"][0]["blob_hash"]
    assert new_hash != original_hash  # actually recaptured, not just left stale

    # and it stays healthy on a third check too -- not just one lucky pass
    refresh_staleness(conn, repo)
    assert get_memory(conn, result["id"])["status"] == "active"


def test_activate_bumps_last_verified_at(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="lesson", scope="repo", confidence="medium",
        statement="Prefer SQLite for this kind of local-first tool.",
    )
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z"
    )
    conn.execute(
        "UPDATE memory SET last_verified_at = ? WHERE id = ?", (old_timestamp, result["id"])
    )

    change_status(conn, repo, result["id"], "active", "still true")

    new_timestamp = get_memory(conn, result["id"])["last_verified_at"]
    assert new_timestamp > old_timestamp


def test_activate_breaks_the_reflag_loop_for_pathless_stale_memory(tmp_path):
    """The path-less side of the same bug: nothing ever advanced
    last_verified_at, so a stale_unverified flag could never clear either."""
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

    change_status(conn, repo, result["id"], "active", "re-read it, still holds")

    # the bug: last_verified_at was never bumped, so this immediately re-flagged
    refresh_staleness(conn, repo)
    memory = get_memory(conn, result["id"])
    assert memory["status"] == "active"
    # holds the manual activation's own reason, not a re-flagged stale_unverified one
    assert memory["status_reason"] == "re-read it, still holds"


def test_attach_evidence_promotion_also_reverifies(tmp_path):
    """The other path to 'active' -- attach_evidence's automatic
    provisional->active promotion -- must reverify too, or a memory whose
    linked path drifted since record time would promote to active while
    still holding a stale stored hash."""
    from robo_cortex.core.evidence import attach_evidence

    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    original_hash = result["paths"][0]["blob_hash"]

    (repo / "src" / "fixture_a" / "exporter.py").write_text(
        'def export_csv(rows): return ",".join(rows)\n'
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "switch delimiter")

    # memory is still 'provisional' -- attach_evidence promotes it, and that
    # promotion must recapture the path hash the same as an explicit activate
    attach_evidence(
        conn, repo, result["id"], kind="free_text",
        description="confirmed current behavior by reading the code",
    )

    memory = get_memory(conn, result["id"])
    assert memory["status"] == "active"
    assert memory["paths"][0]["blob_hash"] != original_hash

    refresh_staleness(conn, repo)
    assert get_memory(conn, result["id"])["status"] == "active"  # does not immediately re-flag
