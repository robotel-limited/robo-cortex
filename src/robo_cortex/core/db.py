import sqlite3
from pathlib import Path

from .errors import BusyError

BUSY_TIMEOUT_MS = 5000
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _translate(error: sqlite3.OperationalError) -> Exception:
    message = str(error).lower()
    if "locked" in message or "busy" in message:
        return BusyError("another writer is active, retry")
    return error


def is_readonly_error(error: Exception) -> bool:
    """Check if an error indicates the database is read-only."""
    message = str(error).lower()
    return "readonly" in message or "read-only" in message


def connect(db_path: Path, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open a connection with autocommit (manual transaction control) and a busy_timeout."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def execute(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Cursor:
    """conn.execute, with SQLITE_BUSY translated to a clear, typed error."""
    try:
        return conn.execute(sql, params)
    except sqlite3.OperationalError as error:
        raise _translate(error) from error


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order, each in its own transaction.

    Idempotent by construction: a migration only runs if its file version is
    greater than the database's current PRAGMA user_version, so re-running
    this on an already-current database (or a fresh one after a prior run)
    is a no-op. Works identically from empty and from an existing schema.

    foreign_keys is turned off for the duration of each migration script and
    verified with a post-migration foreign_key_check. It must be off before
    the script's own BEGIN, since SQLite ignores this pragma once a
    transaction is already open -- and a migration that rebuilds a
    referenced table (create-copy-drop-rename, the only way to change a
    CHECK constraint) would otherwise have its own DROP TABLE silently
    cascade-delete every row in the tables that reference it, since SQLite
    applies ON DELETE actions for a DROP TABLE same as for an explicit
    DELETE when foreign_keys is on. Caught by testing a table-rebuild
    migration against a populated fixture DB before release -- the child
    rows in evidence/memory_link/memory_path were wiped silently, no error
    raised.

    If the script itself fails partway through (bad SQL, SQLITE_BUSY from a
    concurrent writer), its own BEGIN never reaches its COMMIT -- so this
    rolls back explicitly before re-enabling foreign_keys, since that pragma
    is *also* a no-op while a transaction is open. Skipping the rollback
    would leave FK enforcement silently disabled on this connection for
    good, a worse bug than the one this guards against.
    """
    try:
        version = current_version(conn)
        for path in _migration_files():
            file_version = int(path.name.split("_", 1)[0])
            if file_version <= version:
                continue
            sql = path.read_text()
            script = f"BEGIN;\n{sql}\nPRAGMA user_version = {file_version};\nCOMMIT;"
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.executescript(script)
            except BaseException:
                # The script's own BEGIN never reached its COMMIT, so an
                # explicit rollback is required to close that transaction --
                # without it, the PRAGMA foreign_keys = ON below is a no-op
                # (SQLite ignores that pragma while a transaction is open),
                # leaving FK enforcement silently disabled on this connection
                # for good, a worse bug than the one this guards against.
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"migration {file_version} left dangling foreign keys: {violations}"
                )
            version = file_version
        return version
    except sqlite3.OperationalError as error:
        raise _translate(error) from error
