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
    return conn
