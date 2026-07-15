import pytest

from robo_cortex.core.db import connect, current_version, execute, migrate
from robo_cortex.core.errors import BusyError


def test_migrate_from_empty_creates_schema(tmp_path):
    conn = connect(tmp_path / "memory.db")
    version = migrate(conn)
    assert version == 3
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
    assert version_again == 3
    assert current_version(conn) == 3
    conn.close()


def test_migrate_is_idempotent_across_reopened_connections(tmp_path):
    db_path = tmp_path / "memory.db"

    first = connect(db_path)
    migrate(first)
    first.close()

    second = connect(db_path)
    version = migrate(second)
    assert version == 3
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
