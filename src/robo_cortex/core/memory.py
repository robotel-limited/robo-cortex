import json
import sqlite3
from pathlib import Path

from . import db as dbmod
from .abstractor import generate_abstract
from .errors import AmbiguousIdError, NotFoundError, ValidationError
from .git import blob_hash_at_head, working_tree_hash
from .text import fts_query_string, tokenize_without_stopwords

TYPES = {
    "fact", "decision", "convention", "hypothesis",
    "experiment", "lesson", "open_question",
}
SCOPES = {"repo", "global"}
CONFIDENCES = {"low", "medium", "high"}

STATEMENT_MAX = 750
WHY_IT_MATTERS_MAX = 300
ASSUMPTIONS_MAX = 750

# Live working knowledge vs. final/terminal history -- shared by retrieve.py
# (ranking candidate set) and invalidate.py (what the staleness refresh and
# `affected` touch), defined here since both of those modules already
# depend on memory.py and putting it in either one would make the other
# import "sideways".
ACTIVE_LIKE_STATUSES = ("active", "provisional", "needs_review")
EXCLUDED_STATUSES = ("superseded", "invalidated", "abandoned", "archived")

DUPLICATE_SIMILARITY_THRESHOLD = 0.6

_MEMORY_COLUMNS = [
    "id", "type", "scope", "statement", "why_it_matters", "abstract", "assumptions",
    "status", "status_reason", "confidence", "created_at",
    "last_verified_at", "created_by", "use_count", "last_used_at", "valid_until",
]


def _validate_valid_until(valid_until: str | None) -> None:
    """`valid_until` is an optional ISO-8601 timestamp (same shape as
    `created_at`/`last_verified_at`). `valid_from` is deliberately not a
    separate field -- `created_at` already marks when a memory became
    valid (Sorin's call, 2026-11-07): a memory is valid from the moment
    it's recorded until `valid_until` (or forever, if NULL)."""
    if valid_until is None:
        return
    from datetime import datetime
    try:
        datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(
            f"valid_until must be an ISO-8601 timestamp (e.g. '2027-01-01T00:00:00Z'), got {valid_until!r}"
        ) from error


def validate_memory_fields(type_, scope, statement, confidence, why_it_matters, assumptions):
    if type_ not in TYPES:
        raise ValidationError(f"invalid type {type_!r}; must be one of {sorted(TYPES)}")
    if scope not in SCOPES:
        raise ValidationError(f"invalid scope {scope!r}; must be one of {sorted(SCOPES)}")
    if confidence not in CONFIDENCES:
        raise ValidationError(
            f"invalid confidence {confidence!r}; must be one of {sorted(CONFIDENCES)}"
        )
    if not statement or not statement.strip():
        raise ValidationError("statement must not be empty")
    if len(statement) > STATEMENT_MAX:
        raise ValidationError(
            f"statement exceeds {STATEMENT_MAX} characters ({len(statement)})"
        )
    if why_it_matters is not None and len(why_it_matters) > WHY_IT_MATTERS_MAX:
        raise ValidationError(
            f"why_it_matters exceeds {WHY_IT_MATTERS_MAX} characters ({len(why_it_matters)})"
        )
    has_assumptions = assumptions is not None and assumptions.strip() != ""
    if has_assumptions and scope != "global":
        raise ValidationError(
            "assumptions is only meaningful for scope='global' "
            f"(got scope={scope!r})"
        )
    if scope == "global" and not has_assumptions:
        # A global lesson with no (or blank) assumptions clears the §5.4
        # gate vacuously -- assumptions_gate() passes trivially when there's
        # nothing to fail to corroborate -- and gets suggested in every
        # context, exactly the "project-specific win silently becomes a
        # universal rule" failure the gate exists to prevent. Proven live.
        raise ValidationError(
            "scope='global' memories require non-empty assumptions -- state "
            "the conditions under which this lesson applies (e.g. "
            "'single-user, local-first')"
        )
    if has_assumptions and len(assumptions) > ASSUMPTIONS_MAX:
        raise ValidationError(
            f"assumptions exceeds {ASSUMPTIONS_MAX} characters ({len(assumptions)})"
        )


def _statement_similarity(a: str, b: str) -> float:
    """Jaccard token overlap -- a simple, deterministic, absolute (not
    ranking-relative) similarity signal for duplicate detection. FTS5 bm25
    is used elsewhere for *ranking* a candidate set against each other, not
    for an absolute yes/no threshold, since its raw scale isn't calibrated
    for that; this is."""
    tokens_a = set(tokenize_without_stopwords(a))
    tokens_b = set(tokenize_without_stopwords(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _detect_duplicates(conn, memory_id: int, scope: str, statement: str) -> None:
    """ARCHITECTURE.md §6: FTS finds candidates cheaply, Jaccard similarity
    decides. Above threshold -> a duplicate_of link is written automatically
    -- never auto-merged, just flagged for `list --needs-consolidation`.
    """
    query = fts_query_string(statement)
    if not query:
        return
    candidates = conn.execute(
        "SELECT m.id, m.statement FROM memory_fts JOIN memory m ON m.id = memory_fts.rowid "
        "WHERE memory_fts MATCH ? AND m.scope = ? AND m.status IN ('active', 'provisional') "
        "AND m.id != ?",
        (query, scope, memory_id),
    ).fetchall()
    for candidate_id, candidate_statement in candidates:
        if _statement_similarity(statement, candidate_statement) >= DUPLICATE_SIMILARITY_THRESHOLD:
            try:
                conn.execute(
                    "INSERT INTO memory_link (from_id, to_id, link_type) VALUES (?, ?, 'duplicate_of')",
                    (memory_id, candidate_id),
                )
            except sqlite3.IntegrityError:
                pass  # already linked


def record_memory(
    conn,
    repo_root: Path | None,
    *,
    type: str,
    scope: str,
    statement: str,
    confidence: str,
    why_it_matters: str | None = None,
    assumptions: str | None = None,
    paths: list[str] | None = None,
    created_by: str | None = None,
    lesson_from: int | None = None,
    valid_until: str | None = None,
) -> dict:
    """Create a memory. Validates everything, including that every linked
    path exists at HEAD, before writing anything — a dead link is refused
    loudly and no row is ever left half-created.

    `lesson_from`: dead-end compression (ARCHITECTURE.md §6) — recording a
    `lesson` and linking it back to the `abandoned` memory it compresses is
    one call, not two separate record+link calls.

    `valid_until` (migration 0006): optional ISO-8601 timestamp after which
    this memory is stale. NULL (the default) means no expiry. Surfaced by
    `get_memory`/`retrieve_context` as `expired: true` once past; not
    auto-excluded from ranking -- the caller/agent decides what to do with
    an expired-but-returned item, same fail-open posture as `abstract`.
    """
    validate_memory_fields(type, scope, statement, confidence, why_it_matters, assumptions)
    _validate_valid_until(valid_until)

    if lesson_from is not None and type != "lesson":
        raise ValidationError("lesson_from is only valid when type='lesson'")

    paths = paths or []
    if scope == "global" and paths:
        raise ValidationError(
            "scope='global' memories cannot have linked paths -- a path is "
            "repo-relative and a reusable lesson must generalize beyond one "
            "repository (record the originating context as free-text evidence instead)"
        )
    resolved_paths = [(path, blob_hash_at_head(repo_root, path)) for path in paths]

    if lesson_from is not None:
        get_memory(conn, lesson_from)  # existence check, raises NotFoundError

    # Synchronous local-Ollama call -- deliberately outside the transaction
    # below: it's a network call, and a sqlite BEGIN must never stay open
    # across one. generate_abstract() is fail-open by itself (never raises),
    # so no try/except is needed here.
    abstract = generate_abstract(statement)

    conn.execute("BEGIN")
    try:
        cursor = dbmod.execute(
            conn,
            "INSERT INTO memory "
            "(type, scope, statement, why_it_matters, abstract, assumptions, confidence, created_by, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (type, scope, statement, why_it_matters, abstract, assumptions, confidence, created_by, valid_until),
        )
        memory_id = cursor.lastrowid
        for path, blob_hash in resolved_paths:
            dbmod.execute(
                conn,
                "INSERT INTO memory_path (memory_id, path, blob_hash) VALUES (?, ?, ?)",
                (memory_id, path, blob_hash),
            )
        if lesson_from is not None:
            dbmod.execute(
                conn,
                "INSERT INTO memory_link (from_id, to_id, link_type) VALUES (?, ?, 'lesson_from')",
                (memory_id, lesson_from),
            )
        _detect_duplicates(conn, memory_id, scope, statement)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {
        "id": memory_id,
        "status": "provisional",
        "paths": [{"path": path, "blob_hash": blob_hash} for path, blob_hash in resolved_paths],
    }


def record_batch(conn, repo_root: Path, lines: list[str]) -> dict:
    """`record` for each JSON Lines payload. Per-line errors are reported;
    valid lines still commit — this is not all-or-nothing across the batch,
    but each individual line is atomic (record_memory validates every path
    before writing, so a bad line never leaves a partial memory behind).
    """
    created_ids: list[int] = []
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
        if payload.get("scope") == "global":
            # record_batch always writes into the local store passed in by
            # the CLI (repo-scoped bulk seeding is its whole purpose); a
            # scope='global' line would otherwise silently write a
            # global-scoped row into the wrong physical file. Use plain
            # `record --scope global` instead, which routes to
            # ~/.cortex/global.db.
            failed.append({
                "line": line_number,
                "error": "scope='global' is not supported in --batch; use "
                         "'record --scope global' directly for reusable lessons",
            })
            continue
        try:
            result = record_memory(conn, repo_root, **payload)
            created_ids.append(result["id"])
        except TypeError as error:
            failed.append({"line": line_number, "error": f"invalid fields: {error}"})
        except ValidationError as error:
            failed.append({"line": line_number, "error": str(error)})

    return {"created": len(created_ids), "created_ids": created_ids, "failed": failed}


def _is_expired(valid_until: str | None) -> bool:
    if valid_until is None:
        return False
    from datetime import datetime, timezone
    return datetime.fromisoformat(valid_until.replace("Z", "+00:00")) < datetime.now(timezone.utc)


def get_memory(conn, memory_id: int) -> dict:
    row = conn.execute(
        f"SELECT {', '.join(_MEMORY_COLUMNS)} FROM memory WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"no memory with id {memory_id}")

    data = dict(zip(_MEMORY_COLUMNS, row))
    data["expired"] = _is_expired(data["valid_until"])

    path_rows = conn.execute(
        "SELECT path, blob_hash FROM memory_path WHERE memory_id = ? ORDER BY path",
        (memory_id,),
    ).fetchall()
    data["paths"] = [{"path": path, "blob_hash": blob_hash} for path, blob_hash in path_rows]

    evidence_rows = conn.execute(
        "SELECT id, kind, description, command, expected_outcome, ref, status, "
        "created_at, checked_at FROM evidence WHERE memory_id = ? ORDER BY id",
        (memory_id,),
    ).fetchall()
    evidence_columns = [
        "id", "kind", "description", "command", "expected_outcome",
        "ref", "status", "created_at", "checked_at",
    ]
    evidence = [dict(zip(evidence_columns, row)) for row in evidence_rows]
    for item in evidence:
        if item["kind"] == "cold_storage_ref" and item["ref"] is not None:
            content_row = conn.execute(
                "SELECT content FROM cold_storage WHERE id = ?", (item["ref"],)
            ).fetchone()
            item["cold_storage_content"] = content_row[0] if content_row else None
    data["evidence"] = evidence

    link_rows = conn.execute(
        "SELECT link_type, to_id, 'outgoing' FROM memory_link WHERE from_id = ? "
        "UNION ALL "
        "SELECT link_type, from_id, 'incoming' FROM memory_link WHERE to_id = ?",
        (memory_id, memory_id),
    ).fetchall()
    data["links"] = [
        {"link_type": link_type, "memory_id": other_id, "direction": direction}
        for link_type, other_id, direction in link_rows
    ]

    return data


def find_memory_store(local_conn, global_conn, memory_id: int, scope: str | None = None):
    """Which connection actually has this id: local store id sequences and
    the global store's are independent autoincrement counters, so the same
    id can legitimately exist in both, referring to unrelated memories --
    proven live: a local id 1 makes global id 1 unreachable by id from that
    repo without a way to say which store you mean.

    `scope=None` (default): look in both stores. Exactly one hit resolves
    unambiguously. Both hit -> AmbiguousIdError instead of silently picking
    one -- an earlier version silently preferred local here, which is what
    let `roco status 10 activate` flip an unrelated repo-scoped memory
    instead of the intended global one, live, with no error and no
    indication anything had gone wrong (see prompt-bug-roco.md). Neither
    hit -> NotFoundError. `scope='repo'` / `scope='global'`: look only in
    that store, no fallback -- the explicit disambiguator for when the
    caller already knows which memory they mean.

    Used by every ID-taking command (`show`, `status`, `evidence
    add/verify`, `link`) so a scope='global' memory recorded once is still
    reachable by id from any repo afterward, unambiguously when it matters.

    `local_conn` may be `None` -- the caller wasn't inside an initialized
    repo store (see `cli._common._store_or_none`), which is fine for a
    scope='global' lookup but not for an explicit `scope='repo'` one.
    """
    if scope == "repo":
        if local_conn is None:
            raise NotFoundError(
                f"no memory with id {memory_id}: no repo store available "
                "(not inside a git repo, or 'robo-cortex init' never ran "
                "there) -- pass --repo, or drop --scope repo to also check "
                "the global store"
            )
        get_memory(local_conn, memory_id)
        return local_conn
    if scope == "global":
        if global_conn is None:
            raise NotFoundError(f"no memory with id {memory_id}")
        get_memory(global_conn, memory_id)
        return global_conn

    local_hit = local_conn is not None and _has_memory(local_conn, memory_id)
    global_hit = global_conn is not None and _has_memory(global_conn, memory_id)

    if local_hit and global_hit:
        raise AmbiguousIdError(
            f"id {memory_id} exists in both repo and global stores -- "
            "pass --scope repo or --scope global to disambiguate"
        )
    if local_hit:
        return local_conn
    if global_hit:
        return global_conn
    raise NotFoundError(f"no memory with id {memory_id}")


def _has_memory(conn, memory_id: int) -> bool:
    try:
        get_memory(conn, memory_id)
        return True
    except NotFoundError:
        return False


def reverify(conn, repo_root: Path, memory_id: int) -> None:
    """Re-verification: recapture the current blob hash of every linked
    path and bump `last_verified_at` to now.

    ARCHITECTURE.md §5.3 promises hash capture "at record and at verify" --
    this is the "at verify" half, which had never actually been wired up
    anywhere. Without it, moving a memory to `active` only ever cleared the
    status column: the stored blob hash stayed at whatever it was when the
    memory was flagged, so the very next `retrieve`/`search`/`affected`
    call re-compared that same stale hash against HEAD and re-flagged
    `needs_review` immediately -- a human or agent saying "I checked, it's
    still true" had no way to make that stick. Path-less memories have the
    identical bug from the other side: nothing ever advanced
    `last_verified_at` past record time, so a `stale_unverified` flag
    (age-based, one-directional by design, §5.3) could never be cleared
    either, since "verify" never actually recorded when.

    Called whenever a memory transitions to `active` -- the only status
    reachable from both `provisional` and `needs_review` (§4), and the one
    that means "current, as of now" either way.

    Hashes from the working tree (on-disk content), not HEAD: the
    documented recovery from a pre-commit block is `activate` *then*
    re-run `git commit`, while the fix is still staged and HEAD hasn't
    moved yet. Capturing HEAD there is a no-op -- it recomputes the exact
    pre-edit hash the hook already flagged, so the very next `hooks check`
    (comparing against staged content) re-blocks with the identical list,
    and nothing short of `--no-verify` gets past it. `git add` mirrors
    on-disk content into the index, so working-tree and staged hashes
    agree in the normal case; this also matches the already-committed
    case (working tree == HEAD then), so it doesn't change behavior there.
    Falls back to HEAD only if the path is missing on disk (e.g. an
    unstaged deletion), preserving the old not-found error for a path
    genuinely gone at HEAD too.
    """
    path_rows = conn.execute(
        "SELECT path FROM memory_path WHERE memory_id = ?", (memory_id,)
    ).fetchall()
    for (path,) in path_rows:
        new_hash = working_tree_hash(repo_root, path)
        if new_hash is None:
            new_hash = blob_hash_at_head(repo_root, path)
        conn.execute(
            "UPDATE memory_path SET blob_hash = ? WHERE memory_id = ? AND path = ?",
            (new_hash, memory_id, path),
        )
    conn.execute(
        "UPDATE memory SET last_verified_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ?",
        (memory_id,),
    )


def list_memories(
    conn,
    *,
    status: str | None = None,
    scope: str | None = None,
    type: str | None = None,
    needs_consolidation: bool = False,
    abandoned_without_lesson: bool = False,
) -> list[dict]:
    columns = ["id", "type", "scope", "statement", "status", "confidence", "last_verified_at"]
    query = f"SELECT DISTINCT m.{', m.'.join(columns)} FROM memory m WHERE 1 = 1"
    params: list = []
    if status:
        query += " AND m.status = ?"
        params.append(status)
    if scope:
        query += " AND m.scope = ?"
        params.append(scope)
    if type:
        query += " AND m.type = ?"
        params.append(type)
    if needs_consolidation:
        query += (
            " AND m.id IN (SELECT from_id FROM memory_link WHERE link_type = 'duplicate_of' "
            "UNION SELECT to_id FROM memory_link WHERE link_type = 'duplicate_of')"
        )
    if abandoned_without_lesson:
        query += (
            " AND m.status = 'abandoned' AND m.id NOT IN "
            "(SELECT to_id FROM memory_link WHERE link_type = 'lesson_from')"
        )
    query += " ORDER BY m.id"

    rows = conn.execute(query, params).fetchall()
    return [dict(zip(columns, row)) for row in rows]
