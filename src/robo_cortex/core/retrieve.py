from datetime import datetime, timezone

from .assumptions import assumptions_gate
from .errors import ValidationError
from .evidence import evidence_strength
from .invalidate import refresh_staleness
from .memory import EXCLUDED_STATUSES, find_memory_store, get_memory
from .text import fts_query_string

DEFAULT_BUDGET_ITEMS = 15
DEFAULT_BUDGET_TOKENS = 2000
DEFAULT_SEARCH_LIMIT = 50
FTS_CANDIDATE_LIMIT = 200

# ARCHITECTURE.md §5.1 -- weights always sum to 1.0.
WEIGHTS = {
    "text_match": 0.35,
    "path_overlap": 0.20,
    "confidence": 0.15,
    "evidence": 0.15,
    "status": 0.10,
    "recency": 0.05,
}

CONFIDENCE_WEIGHTS = {"low": 0.33, "medium": 0.66, "high": 1.0}
STATUS_WEIGHTS = {"active": 1.0, "provisional": 1.0, "needs_review": 0.7}
RECENCY_HALF_LIFE_DAYS = 90

_EXCLUDED_PLACEHOLDERS = ",".join("?" for _ in EXCLUDED_STATUSES)


def _record_usage(returned: list[tuple], now: datetime) -> tuple[bool, list[str]]:
    """Update use_count and last_used_at for each memory in the returned set.

    Batched per connection to minimize writes: one UPDATE per store, not per row.
    Only touches memories that actually made it into the result (after budget
    filtering), not all candidates that were scored. Gracefully handles read-only
    databases by skipping the write and returning a warning.

    Returns: (success: bool, warnings: list[str])

    Future follow-ups (when usage-based pruning is implemented):
    - Add CREATE INDEX idx_memory_last_used_at ON memory (last_used_at) for
      efficient "find unused since N days ago" queries (full table scan is ok now).
    - Verify that _cmd_merge() (cli.py) exports use_count and last_used_at in
      JSONL format for backup/recovery workflows (needed by prune --backup flow).
    """
    import sqlite3
    from collections import defaultdict
    from .db import is_readonly_error

    by_conn = defaultdict(list)
    for item_conn, memory, _components in returned:
        by_conn[item_conn].append(memory["id"])

    now_str = now.isoformat().replace("+00:00", "Z")
    warnings = []
    for conn, memory_ids in by_conn.items():
        try:
            placeholders = ",".join("?" * len(memory_ids))
            conn.execute(
                f"UPDATE memory SET use_count = use_count + 1, last_used_at = ? "
                f"WHERE id IN ({placeholders})",
                [now_str, *memory_ids],
            )
        except (sqlite3.OperationalError, OSError) as error:
            if is_readonly_error(error):
                warnings.append("store read-only: usage not recorded")
            else:
                raise

    return len(warnings) == 0, warnings


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 if text else 0


def _rendered_item_text(memory: dict) -> str:
    """§5.2: token estimate covers "the full rendered item including
    evidence summaries" -- not just the statement."""
    parts = [memory["statement"]]
    if memory["why_it_matters"]:
        parts.append(memory["why_it_matters"])
    for item in memory.get("evidence", []):
        parts.append(item["description"])
    return " ".join(parts)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _recency_score(last_verified_at: str, now: datetime) -> float:
    verified = _parse_timestamp(last_verified_at)
    age_days = max(0.0, (now - verified).total_seconds() / 86400)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _paths_overlap(a: str, b: str) -> bool:
    if a == b:
        return True
    a_dir, b_dir = a.rstrip("/") + "/", b.rstrip("/") + "/"
    return b.startswith(a_dir) or a.startswith(b_dir)


def _path_overlap_score(task_paths: list[str], memory_paths: list[str]) -> float:
    if not task_paths or not memory_paths:
        return 0.0
    matched = sum(
        1 for task_path in task_paths
        if any(_paths_overlap(task_path, memory_path) for memory_path in memory_paths)
    )
    return matched / len(task_paths)


def _is_contradicted(conn, memory_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM memory_link WHERE link_type = 'contradicts' "
        "AND (from_id = ? OR to_id = ?) LIMIT 1",
        (memory_id, memory_id),
    ).fetchone()
    return row is not None


def score_components(conn, memory: dict, task_paths: list[str], text_match: float, now: datetime) -> dict:
    memory_paths = [p["path"] for p in memory["paths"]]
    components = {
        "text_match": text_match,
        "path_overlap": _path_overlap_score(task_paths, memory_paths),
        "confidence": CONFIDENCE_WEIGHTS[memory["confidence"]],
        "evidence": evidence_strength(conn, memory["id"]),
        # .get(..., 0.0): score_components is also used by explain_memory_score
        # (show --explain-against) on a memory that fell outside the ranking
        # candidate set, which can be a terminal status STATUS_WEIGHTS never
        # covers (they're excluded from ranking, not scored at 0 within it) --
        # explain must still render a number instead of crashing.
        "status": STATUS_WEIGHTS.get(memory["status"], 0.0),
        "recency": _recency_score(memory["last_verified_at"], now),
    }
    components["total"] = sum(WEIGHTS[key] * value for key, value in components.items())
    return components


def _fts_candidates(conn, task: str, scope: str) -> list[tuple[int, float]]:
    fts_query = fts_query_string(task)
    if not fts_query:
        return []
    return conn.execute(
        f"""
        SELECT m.id, bm25(memory_fts) AS raw_score
        FROM memory_fts
        JOIN memory m ON m.id = memory_fts.rowid
        WHERE memory_fts MATCH ? AND m.scope = ?
          AND m.status NOT IN ({_EXCLUDED_PLACEHOLDERS})
        ORDER BY raw_score
        LIMIT ?
        """,
        (fts_query, scope, *EXCLUDED_STATUSES, FTS_CANDIDATE_LIMIT),
    ).fetchall()


def _normalized_scores(rows: list[tuple[int, float]]) -> dict[int, float]:
    """Min-max normalize bm25 within one store's candidate set (lower raw
    bm25 -- better match -- maps closer to 1). Local and global stores are
    normalized independently since they're separate FTS corpora with
    unrelated raw score distributions; a 1.0 in a weak candidate set still
    isn't the same "goodness" as a 1.0 in a strong one, the same caveat the
    single-store case already carries (§5.1), now doubled across stores.
    Documented, not solved -- an absolute relevance measure is future scope.
    """
    if not rows:
        return {}
    raw_scores = [raw for _id, raw in rows]
    lo, hi = min(raw_scores), max(raw_scores)

    def _norm(raw: float) -> float:
        return 1.0 if hi == lo else (hi - raw) / (hi - lo)

    return {memory_id: _norm(raw) for memory_id, raw in rows}


def _score_all_candidates(
    local_conn, task: str, task_paths: list[str], global_conn=None
) -> tuple[list[tuple], list[dict]]:
    """Every candidate matching task's FTS query across both stores, scored
    but not yet budget-truncated or ranked-sorted. Each item is
    (conn, memory, components) -- the conn travels with the memory because
    evidence/contradiction lookups (score_components, _is_contradicted) must
    query the store the memory actually lives in, and local/global ids are
    independent sequences that can collide.

    Scope-B (global) candidates pass through the assumptions gate (§5.4)
    first -- a precondition for candidacy, not a ranking input -- and carry
    their gate result in `components["assumptions_gate"]` when they pass.
    Shared by retrieve_context (packs and sorts this) and explain_memory_score
    (looks a specific memory up in it), so `show --explain-against` and
    `retrieve --explain` can never silently disagree for the same pair.
    """
    now = datetime.now(timezone.utc)
    scored = []
    omitted = []

    local_rows = _fts_candidates(local_conn, task, "repo")
    local_scores = _normalized_scores(local_rows)
    for memory_id, _raw in local_rows:
        memory = get_memory(local_conn, memory_id)
        components = score_components(local_conn, memory, task_paths, local_scores[memory_id], now)
        scored.append((local_conn, memory, components))

    if global_conn is not None:
        global_rows = _fts_candidates(global_conn, task, "global")
        global_scores = _normalized_scores(global_rows)
        for memory_id, _raw in global_rows:
            memory = get_memory(global_conn, memory_id)
            gate = assumptions_gate(memory.get("assumptions"), task)
            if not gate["passed"]:
                omitted.append({"id": memory_id, "scope": "global", "reason": "assumptions_gate"})
                continue
            components = score_components(global_conn, memory, task_paths, global_scores[memory_id], now)
            components["assumptions_gate"] = gate
            scored.append((global_conn, memory, components))

    return scored, omitted


def retrieve_context(
    conn,
    repo_root,
    *,
    task: str,
    paths: list[str] | None = None,
    budget_items: int = DEFAULT_BUDGET_ITEMS,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    explain: bool = False,
    global_conn=None,
) -> dict:
    """The read path: a compact, ranked, budget-honest context pack.

    Consults the local (scope='repo') store always, and the global
    (scope='global') store when `global_conn` is given (Stage 8) --
    candidates from each are gated/scored independently and merged into
    one ranked list. Omitting `global_conn` (the default) reproduces the
    Stage 5-7 local-only behavior exactly, which is what every earlier
    test still exercises.

    Runs the staleness refresh first (§5.3): retrieve is one of the
    documented lazy-check trigger points, so status is always current
    before ranking reads it.
    """
    if not task or not task.strip():
        raise ValidationError("task must not be empty")

    refresh_staleness(conn, repo_root)

    task_paths = paths or []
    if not fts_query_string(task):
        raise ValidationError("task must contain at least one searchable word")

    now = datetime.now(timezone.utc)
    scored, gate_omitted = _score_all_candidates(conn, task, task_paths, global_conn)
    
    # matched includes what survived FTS and assumptions gate
    matched = len(scored)
    
    if matched == 0 and not gate_omitted:
        return {
            "data": [],
            "meta": {
                "matched": 0, "returned": 0, "omitted": [],
                "needs_review": 0, "contradicted": 0,
            },
        }

    scored.sort(key=lambda triple: (-triple[2]["total"], triple[1]["id"]))

    returned: list[tuple] = []
    running_tokens = 0
    for item_conn, memory, components in scored:
        if len(returned) >= budget_items:
            break
        item_tokens = _estimate_tokens(_rendered_item_text(memory))
        if running_tokens + item_tokens > budget_tokens:
            break
        running_tokens += item_tokens
        returned.append((item_conn, memory, components))

    omitted_count = matched - len(returned)
    omitted = [{"reason": "budget", "count": omitted_count}] if omitted_count else []
    if gate_omitted:
        omitted.append({"reason": "assumptions_gate", "count": len(gate_omitted)})

    needs_review = sum(1 for _c, memory, _comp in returned if memory["status"] == "needs_review")
    contradicted = sum(1 for item_conn, memory, _comp in returned if _is_contradicted(item_conn, memory["id"]))

    _success, usage_warnings = _record_usage(returned, now)

    data = []
    for _item_conn, memory, components in returned:
        item = {
            "id": memory["id"],
            "scope": memory["scope"],
            "type": memory["type"],
            "statement": memory["statement"],
            "why_it_matters": memory["why_it_matters"],
            "status": memory["status"],
            "confidence": memory["confidence"],
            "score": components["total"],
        }
        if explain:
            item["score_breakdown"] = components
        data.append(item)

    meta = {
        "matched": matched,
        "returned": len(returned),
        "omitted": omitted,
        "needs_review": needs_review,
        "contradicted": contradicted,
    }
    if usage_warnings:
        meta["warnings"] = usage_warnings
    if explain and gate_omitted:
        meta["omitted_details"] = gate_omitted

    return {
        "data": data,
        "meta": meta,
    }


def _search_one_store(conn, fts_query: str, scope: str | None, type: str | None, status: str | None):
    sql = (
        "SELECT m.id, m.type, m.scope, m.statement, m.status, bm25(memory_fts) AS raw_score "
        "FROM memory_fts JOIN memory m ON m.id = memory_fts.rowid "
        "WHERE memory_fts MATCH ?"
    )
    params: list = [fts_query]
    if scope:
        sql += " AND m.scope = ?"
        params.append(scope)
    if type:
        sql += " AND m.type = ?"
        params.append(type)
    if status:
        sql += " AND m.status = ?"
        params.append(status)
    sql += " ORDER BY raw_score"
    return conn.execute(sql, params).fetchall()


def search_memory(
    conn,
    repo_root,
    *,
    query: str,
    scope: str | None = None,
    type: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    global_conn=None,
) -> dict:
    """Exploration/debugging search -- broader and less strictly budgeted
    than retrieve_context (MCP_TOOLS.md tool 6): no honesty-envelope
    truncation beyond a plain `limit`, because this path never claims to be
    feeding an agent's live working context. One of the three documented
    lazy-check trigger points (§5.3), so it refreshes staleness too.

    Unlike retrieve_context, global-store results here are **not** gated by
    assumptions: search is an explicit, direct lookup ("what do we have on
    X"), not a proactive suggestion, so the gate that exists to keep
    unprompted cross-project suggestions conservative doesn't apply to a
    query someone typed on purpose. Local and global raw bm25 scores are
    merged and sorted together despite being separate corpora -- an
    acknowledged imprecision acceptable for a debug/explore tool, unlike
    retrieve_context's per-store normalization.
    """
    if not query or not query.strip():
        raise ValidationError("query must not be empty")

    refresh_staleness(conn, repo_root)

    fts_query = fts_query_string(query)
    if not fts_query:
        raise ValidationError("query must contain at least one searchable word")

    rows = []
    if scope in (None, "repo"):
        rows += list(_search_one_store(conn, fts_query, scope, type, status))
    if global_conn is not None and scope in (None, "global"):
        rows += list(_search_one_store(global_conn, fts_query, scope, type, status))

    rows.sort(key=lambda r: r[5])
    rows = rows[:limit]

    data = [
        {"id": r[0], "type": r[1], "scope": r[2], "statement": r[3], "status": r[4]}
        for r in rows
    ]
    return {"data": data, "matched": len(data), "returned": len(data)}


def explain_memory_score(
    local_conn, memory_id: int, task: str, *, global_conn=None, scope: str | None = None
) -> dict:
    """`show --explain-against TASK` (ARCHITECTURE.md §8): the score
    components a memory would get in a real retrieve_context call for this
    exact task -- computed via the same _score_all_candidates path, not a
    separate formula, so the two can never silently disagree. A memory the
    task's FTS query doesn't match at all (or a scope-B memory the
    assumptions gate excludes) gets an honest text_match=0.0 / a visible
    failed gate, not a degenerate 1.0 from a single-item normalization.

    `scope`: disambiguates an id that collides between stores (see
    find_memory_store) -- 'repo' or 'global' looks only in that store.
    """
    conn = find_memory_store(local_conn, global_conn, memory_id, scope=scope)  # existence check, right store

    scored, gate_omitted = _score_all_candidates(local_conn, task, [], global_conn)
    for candidate_conn, memory, components in scored:
        if candidate_conn is conn and memory["id"] == memory_id:
            return components

    memory = get_memory(conn, memory_id)
    now = datetime.now(timezone.utc)
    components = score_components(conn, memory, [], 0.0, now)
    if memory["scope"] == "global":
        components["assumptions_gate"] = assumptions_gate(memory.get("assumptions"), task)
    return components
