import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .errors import NotFoundError, ValidationError
from .git import (
    blob_content,
    blob_hash_at_head,
    blob_hash_at_rev,
    diff_touched_paths,
    head_tree,
    working_tree_hash,
)
from .memory import ACTIVE_LIKE_STATUSES, EXCLUDED_STATUSES, get_memory
from .semantic import python_source_is_semantically_equivalent

STALE_AFTER_DAYS = 180

_EXCLUDED_PLACEHOLDERS = ",".join("?" for _ in EXCLUDED_STATUSES)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_comment_or_whitespace_only_change(repo_root: Path, old_hash: str, new_hash: str) -> bool:
    """True only if both blobs decode and tokenize as equivalent Python.

    Any failure (non-UTF8 content, a syntax error, a .py file that isn't
    actually Python) degrades to False -- "cannot prove this is cosmetic,"
    the fail-safe default that preserves today's flag-everything behavior.
    """
    try:
        old_source = blob_content(repo_root, old_hash).decode("utf-8")
        new_source = blob_content(repo_root, new_hash).decode("utf-8")
        return python_source_is_semantically_equivalent(old_source, new_source)
    except Exception:
        return False


def _check_path(repo_root, path_to_hash, hash_to_paths, path, stored_hash):
    if path in path_to_hash:
        current_hash = path_to_hash[path]
        if current_hash == stored_hash:
            return {"status": "ok"}
        if path.endswith(".py") and _is_comment_or_whitespace_only_change(
            repo_root, stored_hash, current_hash
        ):
            return {"status": "reanchored", "new_hash": current_hash}
        return {"status": "changed", "reason": f"path_changed:{path}"}

    candidates = hash_to_paths.get(stored_hash, [])
    if len(candidates) == 1:
        return {"status": "relinked", "old_path": path, "new_path": candidates[0]}
    return {
        "status": "missing",
        "reason": (
            f"path_missing:{path} — recover with: "
            f"git log --follow --diff-filter=R -- {path}"
        ),
    }


def refresh_staleness(
    conn, repo_root: Path, *, now: datetime | None = None, stale_after_days: int = STALE_AFTER_DAYS
) -> list[dict]:
    """Lazily re-check every non-terminal memory against the current HEAD.

    Path-linked memories: blob hash compared against HEAD; exact-hash
    matches at a new path are auto-relinked (§5.3); mismatches or vanished
    paths (with no exact-hash match elsewhere) flag needs_review with a
    reason (a `path_missing` reason includes the git rename-recovery
    command, for use with `record --update-path`); hashes matching again
    heal the memory back to its pre-flag status. Path-less memories:
    age-based needs_review signal only -- one-directional, since
    staleness-by-calendar never "heals" on its own, only via an explicit
    re-verification (`change_status ... active`, Stage 7).

    Healing only fires for memories this function itself flagged (tracked
    via `pre_review_status` being non-NULL) -- a memory a human/agent
    manually moved to `needs_review` via `change_status` for some other
    reason must not get silently reverted just because its linked paths
    happen to already be consistent.

    Gracefully handles read-only databases by skipping all writes and
    returning an empty changes list.

    Caches HEAD SHA in meta table to skip expensive git ls-tree on consecutive
    calls when HEAD hasn't moved; pathless memories (pur SQL staleness check)
    still run every call since they depend on time, not HEAD.

    Called lazily from retrieve/search/affected, not by a daemon (§5.3).
    Returns the list of changes actually made, for callers that want to
    report them.
    """
    import sqlite3
    from .db import is_readonly_error

    now = now or datetime.now(timezone.utc)

    try:
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        current_head = None

    cached_head = None
    if current_head:
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'last_refresh_head'"
            ).fetchone()
            cached_head = row[0] if row else None
        except sqlite3.OperationalError:
            cached_head = None

    if current_head and current_head == cached_head:
        return []

    path_to_hash, hash_to_paths = head_tree(repo_root)

    placeholders = ",".join("?" for _ in ACTIVE_LIKE_STATUSES)
    memory_rows = conn.execute(
        f"SELECT id, status, pre_review_status, last_verified_at FROM memory "
        f"WHERE status IN ({placeholders})",
        ACTIVE_LIKE_STATUSES,
    ).fetchall()

    changes = []
    readonly = False
    for memory_id, status, pre_review_status, last_verified_at in memory_rows:
        if readonly:
            break

        path_rows = conn.execute(
            "SELECT path, blob_hash FROM memory_path WHERE memory_id = ?",
            (memory_id,),
        ).fetchall()

        if not path_rows:
            try:
                _refresh_pathless(conn, memory_id, status, last_verified_at, now, stale_after_days, changes)
            except (sqlite3.OperationalError, OSError) as error:
                if is_readonly_error(error):
                    readonly = True
                else:
                    raise
            continue

        problems = []
        for path, stored_hash in path_rows:
            check = _check_path(repo_root, path_to_hash, hash_to_paths, path, stored_hash)
            if check["status"] == "relinked":
                try:
                    conn.execute(
                        "UPDATE memory_path SET path = ? WHERE memory_id = ? AND path = ?",
                        (check["new_path"], memory_id, check["old_path"]),
                    )
                    changes.append({
                        "memory_id": memory_id, "type": "relinked",
                        "old_path": check["old_path"], "new_path": check["new_path"],
                    })
                except (sqlite3.OperationalError, OSError) as error:
                    if is_readonly_error(error):
                        readonly = True
                        break
                    raise
            elif check["status"] == "reanchored":
                try:
                    conn.execute(
                        "UPDATE memory_path SET blob_hash = ? WHERE memory_id = ? AND path = ?",
                        (check["new_hash"], memory_id, path),
                    )
                    changes.append({
                        "memory_id": memory_id, "type": "reanchored", "path": path,
                    })
                except (sqlite3.OperationalError, OSError) as error:
                    if is_readonly_error(error):
                        readonly = True
                        break
                    raise
            elif check["status"] in ("changed", "missing"):
                problems.append(check["reason"])

        if readonly:
            break

        if problems:
            reason = "; ".join(problems)
            if status != "needs_review":
                try:
                    conn.execute(
                        "UPDATE memory SET status = 'needs_review', status_reason = ?, "
                        "pre_review_status = ? WHERE id = ?",
                        (reason, status, memory_id),
                    )
                    changes.append({"memory_id": memory_id, "type": "flagged", "reason": reason})
                except (sqlite3.OperationalError, OSError) as error:
                    if is_readonly_error(error):
                        readonly = True
                    else:
                        raise
            else:
                try:
                    conn.execute(
                        "UPDATE memory SET status_reason = ? WHERE id = ?", (reason, memory_id)
                    )
                except (sqlite3.OperationalError, OSError) as error:
                    if is_readonly_error(error):
                        readonly = True
                    else:
                        raise
        elif status == "needs_review" and pre_review_status is not None:
            try:
                conn.execute(
                    "UPDATE memory SET status = ?, status_reason = NULL, pre_review_status = NULL "
                    "WHERE id = ?",
                    (pre_review_status, memory_id),
                )
                changes.append({"memory_id": memory_id, "type": "healed", "status": pre_review_status})
            except (sqlite3.OperationalError, OSError) as error:
                if is_readonly_error(error):
                    readonly = True
                else:
                    raise

    if current_head and not readonly:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("last_refresh_head", current_head),
            )
        except sqlite3.OperationalError:
            pass

    return changes


def _batch_working_hashes(repo_root: Path, paths: list[str]) -> dict[str, str | None]:
    """Batch compute blob hashes for multiple files in working tree.

    Uses `git hash-object --stdin-paths` to compute all hashes in a single
    subprocess call instead of one per file.
    """
    if not paths:
        return {}

    stdin_input = "\n".join(paths)
    result = subprocess.run(
        ["git", "hash-object", "--stdin-paths"],
        cwd=repo_root,
        input=stdin_input,
        capture_output=True,
        text=True,
    )

    hashes: dict[str, str | None] = {}
    if result.returncode == 0:
        hash_lines = result.stdout.strip().split("\n")
        for path, hash_line in zip(paths, hash_lines):
            hashes[path] = hash_line.strip() if hash_line.strip() else None
    else:
        for path in paths:
            hashes[path] = None

    return hashes


def _refresh_pathless(conn, memory_id, status, last_verified_at, now, stale_after_days, changes):
    age_days = (now - _parse_timestamp(last_verified_at)).total_seconds() / 86400
    if age_days > stale_after_days and status != "needs_review":
        reason = f"stale_unverified:{int(age_days)}d"
        conn.execute(
            "UPDATE memory SET status = 'needs_review', status_reason = ?, "
            "pre_review_status = ? WHERE id = ?",
            (reason, status, memory_id),
        )
        changes.append({"memory_id": memory_id, "type": "flagged", "reason": reason})


def update_path(conn, repo_root: Path, memory_id: int, old_path: str, new_path: str) -> dict:
    """Manual recovery path for the case exact-hash auto-relink can't
    handle: a file renamed *and* edited in the same commit (§5.3's
    documented limitation). `new_path` is validated to exist at HEAD the
    same way `record` validates linked paths -- no memory is ever pointed
    at a dead link, including by this command.
    """
    get_memory(conn, memory_id)
    row = conn.execute(
        "SELECT 1 FROM memory_path WHERE memory_id = ? AND path = ?",
        (memory_id, old_path),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"memory {memory_id} has no linked path {old_path!r}")

    new_hash = blob_hash_at_head(repo_root, new_path)
    conn.execute(
        "UPDATE memory_path SET path = ?, blob_hash = ? WHERE memory_id = ? AND path = ?",
        (new_path, new_hash, memory_id, old_path),
    )
    try:
        conn.execute("DELETE FROM meta WHERE key = 'last_refresh_head'")
    except Exception:
        pass
    refresh_staleness(conn, repo_root)
    return get_memory(conn, memory_id)


def add_path(conn, repo_root: Path, memory_id: int, path: str) -> dict:
    """Attach a new linked path to an existing memory.

    Closes the gap `update_path` doesn't cover: `update_path` only relinks
    a path already on the memory, so there was previously no way to attach
    a path *after* recording. `record --path` still refuses a path that
    doesn't exist at HEAD (git.py's `blob_hash_at_head`, no memory is ever
    born dead) -- so the intended flow for a not-yet-committed file is:
    record without --path, commit, then `record <id> --add-path <path>`.
    """
    memory = get_memory(conn, memory_id)
    if memory["scope"] == "global":
        raise ValidationError(
            "scope='global' memories cannot have linked paths -- a path is "
            "repo-relative and a reusable lesson must generalize beyond one "
            "repository (record the originating context as free-text evidence instead)"
        )
    row = conn.execute(
        "SELECT 1 FROM memory_path WHERE memory_id = ? AND path = ?",
        (memory_id, path),
    ).fetchone()
    if row is not None:
        raise ValidationError(f"memory {memory_id} is already linked to path {path!r}")

    new_hash = blob_hash_at_head(repo_root, path)
    conn.execute(
        "INSERT INTO memory_path (memory_id, path, blob_hash) VALUES (?, ?, ?)",
        (memory_id, path, new_hash),
    )
    try:
        conn.execute("DELETE FROM meta WHERE key = 'last_refresh_head'")
    except Exception:
        pass
    refresh_staleness(conn, repo_root)
    return get_memory(conn, memory_id)


def affected(
    conn,
    repo_root: Path,
    *,
    diff_range: str | None = None,
    staged: bool = False,
    working: bool = False,
) -> dict:
    """Memories put at risk by a diff.

    `affected` is one of the three documented lazy-check trigger points
    (§5.3, alongside retrieve/search), so it runs refresh_staleness first --
    anything already committed since the last check gets flagged/healed for
    real, same as a `retrieve` call would. On top of that, it separately
    *reports* (read-only, no mutation) whatever the requested diff touches
    that hasn't been committed yet: a HEAD-vs-stored-hash comparison can't
    see an uncommitted edit, because HEAD hasn't moved, so this half exists
    specifically to surface risk before the commit that would otherwise
    trigger it. Terminal-status memories (superseded/invalidated/abandoned/
    archived) are excluded from the report -- they are not "at risk", they
    are already history.

    Default (no flags): working tree + staged combined (`git diff HEAD`).
    --staged: staged changes only (`git diff --cached`). --working: unstaged
    changes only (`git diff`, no HEAD/--cached). --diff-range A..B: an
    explicit committed range, compared against B's committed content.
    """
    refresh_staleness(conn, repo_root)

    if diff_range:
        diff_args = [diff_range]
        target = diff_range.split("..", 1)[-1].lstrip(".") or "HEAD"
        suffix = diff_range

        def _current_hash(path: str) -> str | None:
            return blob_hash_at_rev(repo_root, target, path)
    else:
        if staged:
            diff_args = ["--cached"]
        elif working:
            diff_args = []
        else:
            diff_args = ["HEAD"]
        suffix = "working_tree"

        def _current_hash(path: str) -> str | None:
            return working_tree_hash(repo_root, path)

    touched_paths = diff_touched_paths(repo_root, diff_args)

    placeholders = ",".join("?" * len(touched_paths))
    linked_rows = conn.execute(
        f"""SELECT mp.path, mp.memory_id, mp.blob_hash, m.statement FROM memory_path mp
           JOIN memory m ON m.id = mp.memory_id
           WHERE mp.path IN ({placeholders})
           AND m.status NOT IN ({_EXCLUDED_PLACEHOLDERS})""",
        [*touched_paths, *EXCLUDED_STATUSES],
    ).fetchall()

    paths_with_memories = {path for path, _mid, _hash, _stmt in linked_rows}
    hashes_to_compute = [p for p in paths_with_memories if p in touched_paths]

    current_hashes: dict[str, str | None] = {}
    if hashes_to_compute:
        if diff_range or not (staged or working):
            for path in hashes_to_compute:
                current_hashes[path] = _current_hash(path)
        elif working:
            current_hashes = _batch_working_hashes(repo_root, hashes_to_compute)
        else:
            for path in hashes_to_compute:
                current_hashes[path] = _current_hash(path)

    data = []
    seen_memory_ids: set[int] = set()
    for path, memory_id, stored_hash, statement in linked_rows:
        if memory_id in seen_memory_ids:
            continue
        current_hash = current_hashes.get(path)
        if current_hash == stored_hash:
            continue
        reason = f"path_missing:{path}" if current_hash is None else f"path_changed:{path}@{suffix}"
        data.append({"id": memory_id, "statement": statement, "reason": reason})
        seen_memory_ids.add(memory_id)

    return {"data": data, "matched": len(data)}
