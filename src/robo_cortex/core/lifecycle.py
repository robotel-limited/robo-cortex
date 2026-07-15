import json
import sqlite3
from pathlib import Path

from .errors import IllegalTransitionError, ValidationError
from .memory import get_memory, reverify, find_memory_store

# ARCHITECTURE.md §4's transition matrix. needs_review -> active appears here
# both as the automatic revert-heal outcome (invalidate.py, gated on
# pre_review_status) and as a valid manual change_status target (e.g.
# clearing a path-less stale_unverified flag, which never self-heals).
#
# active -> abandoned was added post-v0.1.0: attach_evidence auto-promotes
# provisional -> active on first evidence (evidence.py), which otherwise
# made an experiment/hypothesis unabandonable the moment you attached the
# very evidence that shows it was a dead end -- e.g. a benchmark proving a
# caching attempt made things slower. Recording the evidence before calling
# abandon is the natural order; the state machine should not forbid it.
ALLOWED_TRANSITIONS = {
    "provisional": {"active", "needs_review", "abandoned"},
    "active": {"needs_review", "superseded", "invalidated", "archived", "abandoned"},
    "needs_review": {"active", "superseded", "invalidated"},
    "superseded": {"archived"},
    "invalidated": {"archived"},
    "abandoned": {"archived"},
    "archived": set(),
}

LINK_TYPES = {"contradicts", "duplicate_of"}

STATUS_ACTIONS = {
    "supersede": "superseded",
    "invalidate": "invalidated",
    "abandon": "abandoned",
    "archive": "archived",
    "activate": "active",
}


def change_status(
    conn,
    repo_root: Path,
    memory_id: int,
    new_status: str,
    reason: str,
    *,
    supersedes_link_to: int | None = None,
) -> dict:
    memory = get_memory(conn, memory_id)
    current = memory["status"]
    allowed = ALLOWED_TRANSITIONS.get(current, set())

    if new_status not in allowed:
        raise IllegalTransitionError(
            f"cannot transition memory {memory_id} from {current!r} to {new_status!r}; "
            f"allowed from {current!r}: {sorted(allowed) or 'none (terminal)'}"
        )
    if not reason or not reason.strip():
        raise ValidationError("reason is required for a status change")
    if new_status == "superseded" and not supersedes_link_to:
        raise ValidationError(
            "new_status='superseded' requires supersedes_link_to "
            "(a supersession with nothing named as the replacement isn't one)"
        )
    if supersedes_link_to is not None:
        get_memory(conn, supersedes_link_to)  # existence check

    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE memory SET status = ?, status_reason = ?, pre_review_status = NULL "
            "WHERE id = ?",
            (new_status, reason, memory_id),
        )
        if new_status == "superseded":
            conn.execute(
                "INSERT INTO memory_link (from_id, to_id, link_type) VALUES (?, ?, 'supersedes')",
                (memory_id, supersedes_link_to),
            )
        if new_status == "active":
            # "I checked, it's still true" must actually mean something: recapture
            # linked-path hashes and last_verified_at, or the next staleness check
            # re-flags this immediately against the same stale stored hash.
            reverify(conn, repo_root, memory_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {"id": memory_id, "status": new_status}


def status_batch(local_conn, global_conn, repo_root: Path, lines: list[str]) -> dict:
    """`status` for each JSON Lines payload. Per-line errors are reported;
    valid lines still commit — this is not all-or-nothing across the batch.
    Each line must be a JSON object with: id, action, reason; optional: supersedes, scope.
    """
    updated: list[dict] = []
    failed: list[dict] = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            failed.append({"line": line_number, "error": f"invalid JSON: {error}"})
            continue
        if not isinstance(payload, dict):
            failed.append({"line": line_number, "error": "each line must be a JSON object"})
            continue

        memory_id = payload.get("id")
        action = payload.get("action")
        reason = payload.get("reason")
        supersedes = payload.get("supersedes")
        scope = payload.get("scope")

        if memory_id is None:
            failed.append({"line": line_number, "error": "missing 'id'"})
            continue
        if action is None:
            failed.append({"line": line_number, "error": "missing 'action'"})
            continue
        if reason is None:
            failed.append({"line": line_number, "error": "missing 'reason'"})
            continue

        if action not in STATUS_ACTIONS:
            failed.append({"line": line_number, "error": f"invalid action '{action}'; must be one of {sorted(STATUS_ACTIONS)}"})
            continue

        try:
            store = find_memory_store(local_conn, global_conn, memory_id, scope=scope)
            new_status = STATUS_ACTIONS[action]
            result = change_status(store, repo_root, memory_id, new_status, reason, supersedes_link_to=supersedes)
            updated.append(result)
        except (ValueError, TypeError) as error:
            failed.append({"line": line_number, "error": f"invalid fields: {error}"})
        except Exception as error:
            failed.append({"line": line_number, "error": str(error)})

    return {"updated": len(updated), "updated_ids": [u["id"] for u in updated], "failed": failed}


def create_link(conn, from_id: int, to_id: int, link_type: str) -> dict:
    if from_id == to_id:
        raise ValidationError("cannot link a memory to itself")
    if link_type not in LINK_TYPES:
        raise ValidationError(f"invalid link_type {link_type!r}; must be one of {sorted(LINK_TYPES)}")
    get_memory(conn, from_id)
    get_memory(conn, to_id)

    try:
        conn.execute(
            "INSERT INTO memory_link (from_id, to_id, link_type) VALUES (?, ?, ?)",
            (from_id, to_id, link_type),
        )
    except sqlite3.IntegrityError as error:
        raise ValidationError(
            f"a {link_type!r} link between {from_id} and {to_id} already exists"
        ) from error

    return {"from_id": from_id, "to_id": to_id, "link_type": link_type}
