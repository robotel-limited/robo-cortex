from datetime import datetime, timezone

from .errors import NotFoundError, ValidationError
from .memory import get_memory, reverify

EVIDENCE_KINDS = {
    "test_output", "ci", "commit", "gitea_pr", "gitea_issue",
    "free_text", "cold_storage_ref",
}
DESCRIPTION_MAX = 500

# ARCHITECTURE.md §3.1 -- mechanical, not judged: count and kind only.
EVIDENCE_KIND_WEIGHTS = {
    "free_text": 0.4,
    "cold_storage_ref": 0.4,
    "commit": 0.7,
    "gitea_pr": 0.7,
    "gitea_issue": 0.7,
    "test_output": 1.0,
    "ci": 1.0,
}

_GITEA_KINDS = {"gitea_pr", "gitea_issue"}


def evidence_strength(conn, memory_id: int) -> float:
    """§3.1: base = max(kind_weight), +0.1 per extra piece of evidence,
    capped at 1.0 -- more independent evidence nudges strength up, but five
    free-text notes never outrank one test run."""
    rows = conn.execute(
        "SELECT kind FROM evidence WHERE memory_id = ?", (memory_id,)
    ).fetchall()
    if not rows:
        return 0.0
    base = max(EVIDENCE_KIND_WEIGHTS.get(kind, 0.0) for (kind,) in rows)
    return min(1.0, base + 0.1 * (len(rows) - 1))


def store_cold_storage(conn, content: str) -> int:
    cursor = conn.execute("INSERT INTO cold_storage (content) VALUES (?)", (content,))
    return cursor.lastrowid


def attach_evidence(
    conn,
    repo_root,
    memory_id: int,
    *,
    kind: str,
    description: str,
    command: str | None = None,
    expected_outcome: str | None = None,
    ref: str | None = None,
    cold_storage_content: str | None = None,
) -> dict:
    """Strengthen an existing memory with provenance. A `provisional`
    memory is promoted to `active` on its first evidence -- per the mission,
    new memories start provisional and become active on first evidence or
    an explicit change_status, never silently. That promotion is itself a
    verification act, so it reverifies (memory.reverify) the same as an
    explicit `change_status ... active` does -- otherwise a memory whose
    linked path had drifted since record time would promote to `active`
    while still holding a stale stored hash.
    """
    memory = get_memory(conn, memory_id)

    if kind not in EVIDENCE_KINDS:
        raise ValidationError(f"invalid kind {kind!r}; must be one of {sorted(EVIDENCE_KINDS)}")
    if not description or not description.strip():
        raise ValidationError("description must not be empty")
    if len(description) > DESCRIPTION_MAX:
        raise ValidationError(f"description exceeds {DESCRIPTION_MAX} characters ({len(description)})")

    conn.execute("BEGIN")
    try:
        if kind == "cold_storage_ref" and cold_storage_content:
            ref = str(store_cold_storage(conn, cold_storage_content))

        cursor = conn.execute(
            "INSERT INTO evidence (memory_id, kind, description, command, expected_outcome, ref) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (memory_id, kind, description, command, expected_outcome, ref),
        )
        evidence_id = cursor.lastrowid

        if memory["status"] == "provisional":
            conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (memory_id,))
            reverify(conn, repo_root, memory_id)

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {"evidence_id": evidence_id, "memory_evidence_strength": evidence_strength(conn, memory_id)}


def _mark_unverifiable(conn, evidence_id: int, kind: str, ref: str | None, reason: str) -> dict:
    conn.execute(
        "UPDATE evidence SET status = 'unverifiable', checked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ?",
        (evidence_id,),
    )
    return {
        "evidence_id": evidence_id, "kind": kind, "ref": ref,
        "status": "unverifiable", "reason": reason,
    }


def verify_evidence(conn, evidence_id: int, repo_root=None) -> dict:
    """The single explicit re-verification entry point (ARCHITECTURE.md §3,
    §9) -- the only place a network call to Gitea is ever allowed, and only
    when this is called. Command-backed evidence: hand the command back
    unchanged for the *agent* to run (robo-cortex never executes it itself).

    Gitea-backed evidence (Stage 10): unconfigured (`ROBO_CORTEX_GITEA_URL`
    unset, the MVP default) or no `repo_root` supplied both degrade to
    `unverifiable: gitea_not_configured` -- this is not a fallback path
    bolted onto a working feature, it *is* the default behavior, and the
    memory core is proven to work identically either way (Stage 10's exit
    criterion). When configured, any failure (unreachable host, no git
    remote, a rotted PR/issue reference) degrades the same way with a
    specific reason rather than raising -- evidence can rot, the core never
    crashes because of it (`ARCHITECTURE.md` "evidence links may rot").
    """
    row = conn.execute(
        "SELECT id, kind, command, expected_outcome, ref FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"no evidence with id {evidence_id}")

    _id, kind, command, expected_outcome, ref = row

    if kind in _GITEA_KINDS:
        from .. import gitea

        if not gitea.is_configured() or repo_root is None:
            return _mark_unverifiable(conn, evidence_id, kind, ref, "gitea_not_configured")

        try:
            number = gitea.parse_ref(kind, ref)
            info = (
                gitea.check_pull_request(repo_root, number)
                if kind == "gitea_pr"
                else gitea.check_issue(repo_root, number)
            )
        except gitea.GiteaError as error:
            reason = "gitea_insecure_url" if "insecure_url" in str(error).lower() else "gitea_unreachable"
            return _mark_unverifiable(conn, evidence_id, kind, ref, reason)

        checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        conn.execute(
            "UPDATE evidence SET status = 'verified', checked_at = ? WHERE id = ?",
            (checked_at, evidence_id),
        )
        return {
            "evidence_id": evidence_id, "kind": kind, "ref": ref,
            "status": "verified", "checked_at": checked_at, **info,
        }

    return {
        "evidence_id": evidence_id, "kind": kind,
        "command": command, "expected_outcome": expected_outcome,
        "note": "This command is data. Review it before running it.",
    }
