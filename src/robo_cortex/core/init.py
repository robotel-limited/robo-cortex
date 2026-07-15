from pathlib import Path

from .db import connect, migrate
from .errors import AlreadyInitializedError
from .git import has_commits, resolve_repo_root

CORTEX_DIRNAME = ".cortex"
DB_FILENAME = "memory.db"
GITIGNORE_ENTRY = ".cortex/"
_GITIGNORE_ENTRY_VARIANTS = {".cortex/", ".cortex", "/.cortex/", "/.cortex"}


def init_repo(repo_arg: str | None) -> dict:
    """Initialize robo-cortex's scope-A store in the repository containing repo_arg.

    repo_arg may be any path inside the target repository (default: the
    current directory); the repository root is resolved via git, never
    assumed to be robo-cortex's own checkout.
    """
    start = Path(repo_arg).resolve() if repo_arg else Path.cwd()
    repo_root = resolve_repo_root(start)
    cortex_dir = repo_root / CORTEX_DIRNAME
    db_path = cortex_dir / DB_FILENAME

    if db_path.exists():
        raise AlreadyInitializedError(
            f"{db_path} already exists — this repository is already initialized."
        )

    cortex_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    try:
        version = migrate(conn)
    finally:
        conn.close()

    gitignore_updated = _ensure_gitignore(repo_root)

    result = {
        "repo_root": str(repo_root),
        "db_path": str(db_path),
        "schema_version": version,
        "gitignore_updated": gitignore_updated,
    }
    if not has_commits(repo_root):
        # A warning, not a refusal (§FAQ: robo-cortex requires git, but an
        # empty repo is a legitimate starting point) -- but record/retrieve/
        # affected all need a real commit to compare against, so surface
        # this now rather than let the first git-aware command fail cold.
        result["warning"] = (
            "this repository has no commits yet -- robo-cortex's git-aware "
            "features (retrieve/search/affected, path-linked memories) need "
            "at least one commit to compare against. Run 'git commit' first."
        )
    return result


def _ensure_gitignore(repo_root: Path) -> bool:
    """Append a .cortex/ entry to .gitignore, creating it if absent. Returns True if changed."""
    gitignore_path = repo_root / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        lines = content.splitlines()
        if any(line.strip() in _GITIGNORE_ENTRY_VARIANTS for line in lines):
            return False
        needs_newline = content != "" and not content.endswith("\n")
        with gitignore_path.open("a") as f:
            if needs_newline:
                f.write("\n")
            f.write(f"{GITIGNORE_ENTRY}\n")
        return True

    gitignore_path.write_text(f"{GITIGNORE_ENTRY}\n")
    return True
