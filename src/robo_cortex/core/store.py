import os
import sqlite3
from pathlib import Path

from .db import connect, migrate
from .errors import NotInitializedError
from .git import resolve_repo_root
from .init import CORTEX_DIRNAME, DB_FILENAME


def open_store(repo_arg: str | None) -> tuple[Path, sqlite3.Connection]:
    """Resolve the target repository and open its scope-A store.

    Shared by every command that reads or writes memories (record, show,
    list, retrieve, ...) so repo resolution and db-open happen exactly one
    way. Runs the migration chain on every open — a no-op on an
    already-current database — so an older checkout self-upgrades on first
    use instead of needing a separate manual step.
    """
    start = Path(repo_arg).resolve() if repo_arg else Path.cwd()
    repo_root = resolve_repo_root(start)
    db_path = repo_root / CORTEX_DIRNAME / DB_FILENAME
    if not db_path.exists():
        raise NotInitializedError(
            f"{db_path} does not exist. Run 'robo-cortex init' first."
        )
    conn = connect(db_path)
    migrate(conn)
    return repo_root, conn


GLOBAL_DIR = Path.home() / ".cortex"
GLOBAL_DB_FILENAME = "global.db"

# Repo-local stores and the global store share one schema/migration chain,
# so each starts its own autoincrement id sequence at 1 -- meaning a repo
# memory #10 and a global memory #10 can (and did, live) coexist and refer
# to unrelated rows, with nothing to disambiguate a bare id between them
# (see prompt-bug-roco.md). Reserving this range for the global store makes
# new collisions structurally impossible: no realistic single-user repo
# will ever record a billion memories. This only pushes future ids in the
# global store's autoincrement tables above the floor -- it never touches
# already-assigned ids (that would renumber existing memory/evidence rows
# out from under their own FK references and any external reference to
# those ids), so ids assigned before this fix shipped can still collide;
# `find_memory_store`'s AmbiguousIdError is what catches those.
GLOBAL_ID_FLOOR = 1_000_000_000
_GLOBAL_AUTOINCREMENT_TABLES = ("memory", "evidence", "memory_link", "cold_storage")

# Override for tests (and any user who wants a non-default location): a full
# path to the global db file. Without this, every test process would read
# and write the *real* ~/.cortex/global.db on whatever machine runs the
# suite -- silently polluting a real user's actual reusable-lesson store,
# and cross-contaminating test runs with each other's data. The test suite
# sets this in every fixture that touches the global store; production use
# leaves it unset and gets the documented default.
_GLOBAL_DB_ENV_VAR = "ROBO_CORTEX_GLOBAL_DB"
_GLOBAL_DISABLED_ENV_VAR = "ROBO_CORTEX_NO_GLOBAL"


def global_db_path() -> Path:
    override = os.environ.get(_GLOBAL_DB_ENV_VAR)
    return Path(override) if override else GLOBAL_DIR / GLOBAL_DB_FILENAME


def is_global_enabled() -> bool:
    """Check if global store is enabled (not disabled via env var)."""
    return not os.environ.get(_GLOBAL_DISABLED_ENV_VAR)


def open_global_store() -> sqlite3.Connection | None:
    """Open (creating if absent) the scope-B store: ARCHITECTURE.md §2's
    `~/.cortex/global.db`, same schema/migrations as a repo's local store,
    outside any repository by construction -- so unlike `open_store`, this
    needs no repo resolution at all and never fails with "not initialized";
    the first call anywhere creates it.

    Returns None if ROBO_CORTEX_NO_GLOBAL is set (opt-out).
    """
    if not is_global_enabled():
        return None

    db_path = global_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    migrate(conn)
    _ensure_global_id_floor(conn)
    return conn


def _ensure_global_id_floor(conn: sqlite3.Connection) -> None:
    """Bump each autoincrement table's next id up to GLOBAL_ID_FLOOR if it
    isn't already past it. Idempotent (only ever raises seq, never lowers
    it) and a no-op once the floor has been crossed, so it's cheap to call
    on every open rather than needing a one-time migration step.
    """
    for table in _GLOBAL_AUTOINCREMENT_TABLES:
        row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                (table, GLOBAL_ID_FLOOR),
            )
        elif row[0] < GLOBAL_ID_FLOOR:
            conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                (GLOBAL_ID_FLOOR, table),
            )
