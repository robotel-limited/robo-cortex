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
    """
    try:
        version = current_version(conn)
        for path in _migration_files():
            file_version = int(path.name.split("_", 1)[0])
            if file_version <= version:
                continue
            sql = path.read_text()
            script = f"BEGIN;\n{sql}\nPRAGMA user_version = {file_version};\nCOMMIT;"
            conn.executescript(script)
            version = file_version
        return version
    except sqlite3.OperationalError as error:
        raise _translate(error) from error
