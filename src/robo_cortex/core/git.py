import subprocess
from pathlib import Path

from .errors import NotAGitRepoError, ValidationError


def resolve_repo_root(start: Path) -> Path:
    """Find the repository root containing `start` via `git rev-parse --show-toplevel`.

    Never assumes it runs inside robo-cortex's own checkout: the caller
    supplies where to look (defaulting to the current directory), and
    resolution happens entirely through git against that path.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        raise NotAGitRepoError(
            f"{start} is not inside a git repository (robo-cortex requires one). "
            "Run 'git init' first, or pass --repo to point at an existing repository."
        ) from error
    return Path(result.stdout.strip())


def blob_hash_at_head(repo_root: Path, path: str) -> str:
    """git rev-parse HEAD:<path> — the free, no-diff-scanning anchor hash.

    Raises ValidationError if the path does not exist at HEAD: no memory is
    ever born dead (ARCHITECTURE.md §1, mission "automatic maintenance" 1).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{path}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise ValidationError(
            f"path does not exist at HEAD: {path!r} — refusing to link a "
            "memory to a nonexistent path. Commit the file first with 'git add' and "
            "'git commit', or record the memory now without --path and attach it "
            "later with 'record <id> --add-path <path>'."
        ) from error
    return result.stdout.strip()


def has_commits(repo_root: Path) -> bool:
    """Whether HEAD resolves to a real commit -- False for a freshly
    `git init`-ed repo before its first commit. Every git-aware feature
    (staleness refresh, `affected`, path linking) needs at least one
    commit to have something to compare against; this is the one cheap
    check that lets callers say so clearly instead of letting `git
    ls-tree HEAD` fail with a bare exit 128.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def head_tree(repo_root: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Every path -> blob_hash at HEAD, and its reverse index (blob_hash ->
    paths), in one `git ls-tree` call. The reverse index is what makes
    exact-hash rename relinking (ARCHITECTURE.md §5.3) a single lookup
    instead of an N+1 scan.

    Raises ValidationError (not a raw CalledProcessError) if the repository
    has no commits yet -- HEAD doesn't resolve, so there is no tree to walk.
    """
    result = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValidationError(
            "this repository has no commits yet -- robo-cortex's git-aware "
            "features (retrieve/search/affected staleness checks) need at "
            "least one commit to compare against. Run 'git commit' first."
        )
    path_to_hash: dict[str, str] = {}
    hash_to_paths: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        meta, path = line.split("\t", 1)
        _mode, _type, blob_hash = meta.split()
        path_to_hash[path] = blob_hash
        hash_to_paths.setdefault(blob_hash, []).append(path)
    return path_to_hash, hash_to_paths


def working_tree_hash(repo_root: Path, path: str) -> str | None:
    """git hash-object <path> -- the blob hash the file would get if
    committed right now, computed from its current on-disk content without
    needing a commit. None if the file no longer exists on disk.
    """
    if not (repo_root / path).exists():
        return None
    result = subprocess.run(
        ["git", "hash-object", "--", path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def blob_hash_at_rev(repo_root: Path, rev: str, path: str) -> str | None:
    """git rev-parse <rev>:<path>. None if the path doesn't exist at rev
    (deleted, or never existed there)."""
    result = subprocess.run(
        ["git", "rev-parse", f"{rev}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def blob_content(repo_root: Path, blob_hash: str) -> bytes:
    """git cat-file blob <hash> -- raw bytes of a blob by its hash.

    Used by the Python semantic-equivalence check (§5.3's comment/whitespace
    tolerance) to fetch both the stored and current blob content for
    tokenization, without needing either version checked out on disk.
    Raises CalledProcessError if the hash doesn't resolve to a blob.
    """
    result = subprocess.run(
        ["git", "cat-file", "blob", blob_hash],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    return result.stdout


def diff_touched_paths(repo_root: Path, diff_args: list[str]) -> list[str]:
    """git diff --name-only <diff_args> -- paths touched by a diff. Raises
    ValidationError with git's own message if diff_args don't resolve.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", *diff_args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValidationError(f"invalid diff range: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]
