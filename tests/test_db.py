import sqlite3

import pytest

from robo_cortex.core.db import MIGRATIONS_DIR, connect, current_version, execute, migrate
from robo_cortex.core.errors import BusyError


def test_migrate_from_empty_creates_schema(tmp_path):
    conn = connect(tmp_path / "memory.db")
    version = migrate(conn)
    assert version == 5
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"memory", "memory_path", "evidence", "memory_link", "cold_storage"} <= tables
    conn.close()


def test_migrate_is_idempotent_on_same_connection(tmp_path):
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    version_again = migrate(conn)
    assert version_again == 5
    assert current_version(conn) == 5
    conn.close()


def test_migrate_is_idempotent_across_reopened_connections(tmp_path):
    db_path = tmp_path / "memory.db"

    first = connect(db_path)
    migrate(first)
    first.close()

    second = connect(db_path)
    version = migrate(second)
    assert version == 5
    second.close()


def test_migrated_db_accepts_a_row(tmp_path):
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    execute(
        conn,
        "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
        ("fact", "repo", "The scanner batches at 50 items.", "high"),
    )
    row = conn.execute("SELECT statement FROM memory").fetchone()
    assert row[0] == "The scanner batches at 50 items."
    conn.close()


def test_0004_widens_limits_and_preserves_existing_rows_and_fk_integrity(tmp_path):
    """Upgrade path: a DB already on version 3 (pre-0004, 500-char caps),
    carrying rows in every table 0004's rebuild touches or references
    (memory, evidence, memory_path, memory_link), must come out of
    `migrate()` on version 4 with those rows intact, FK-valid, and able to
    accept a statement/description between 501 and 750 chars that version 3
    would have rejected. Exercises the exact failure mode flagged in
    db.py's migrate() docstring: a table-rebuild migration silently
    cascade-deleting referencing rows if foreign_keys isn't off for the
    rebuild.
    """
    conn = connect(tmp_path / "memory.db")
    v3_files = [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if int(p.name.split("_", 1)[0]) <= 3]
    for path in v3_files:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(f"BEGIN;\n{path.read_text()}\nPRAGMA user_version = {path.name.split('_', 1)[0]};\nCOMMIT;")
        conn.execute("PRAGMA foreign_keys = ON")
    assert current_version(conn) == 3

    memory_id = execute(
        conn,
        "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
        ("fact", "repo", "pre-existing memory row", "high"),
    ).lastrowid
    execute(
        conn,
        "INSERT INTO memory_path (memory_id, path, blob_hash) VALUES (?, ?, ?)",
        (memory_id, "src/thing.py", "deadbeef"),
    )
    evidence_id = execute(
        conn,
        "INSERT INTO evidence (memory_id, kind, description) VALUES (?, ?, ?)",
        (memory_id, "free_text", "pre-existing evidence row"),
    ).lastrowid
    other_id = execute(
        conn,
        "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
        ("fact", "repo", "a second memory to link against", "low"),
    ).lastrowid
    execute(
        conn,
        "INSERT INTO memory_link (from_id, to_id, link_type) VALUES (?, ?, ?)",
        (memory_id, other_id, "duplicate_of"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        execute(
            conn,
            "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
            ("fact", "repo", "x" * 600, "low"),
        )

    version = migrate(conn)

    assert version == 5
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute(
        "SELECT statement FROM memory WHERE id = ?", (memory_id,)
    ).fetchone()[0] == "pre-existing memory row"
    assert conn.execute(
        "SELECT path FROM memory_path WHERE memory_id = ?", (memory_id,)
    ).fetchone()[0] == "src/thing.py"
    assert conn.execute(
        "SELECT description FROM evidence WHERE id = ?", (evidence_id,)
    ).fetchone()[0] == "pre-existing evidence row"
    assert conn.execute(
        "SELECT link_type FROM memory_link WHERE from_id = ? AND to_id = ?", (memory_id, other_id)
    ).fetchone()[0] == "duplicate_of"
    assert conn.execute(
        "SELECT statement FROM memory_fts WHERE rowid = ?", (memory_id,)
    ).fetchone()[0] == "pre-existing memory row"

    new_id = execute(
        conn,
        "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
        ("fact", "repo", "x" * 600, "low"),
    ).lastrowid
    assert new_id > other_id
    execute(
        conn,
        "INSERT INTO evidence (memory_id, kind, description) VALUES (?, ?, ?)",
        (new_id, "free_text", "y" * 600),
    )
    conn.close()


def test_busy_writer_surfaces_clear_error_not_a_stack_trace(tmp_path):
    db_path = tmp_path / "memory.db"

    setup = connect(db_path)
    migrate(setup)
    setup.close()

    holder = connect(db_path, busy_timeout_ms=100)
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute(
        "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
        ("fact", "repo", "held by another writer", "low"),
    )

    contender = connect(db_path, busy_timeout_ms=100)
    with pytest.raises(BusyError, match="another writer is active, retry"):
        execute(
            contender,
            "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
            ("fact", "repo", "should be rejected", "low"),
        )

    holder.execute("ROLLBACK")
    holder.close()
    contender.close()
