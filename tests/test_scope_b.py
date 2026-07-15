"""Stage 8: the reusable (scope B) memory store. Uses both fixture repos
(A and B) since the whole point of scope B is retrieval across them.
"""

import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.errors import NotFoundError, ValidationError
from robo_cortex.core.memory import find_memory_store, get_memory, list_memories, record_memory
from robo_cortex.core.retrieve import retrieve_context, search_memory
from robo_cortex.core.store import open_global_store

from .fixtures import build_fixture_repo_a, build_fixture_repo_b


def _repo_a(tmp_path):
    repo = build_fixture_repo_a(tmp_path / "a")
    conn = connect(tmp_path / "a.db")
    migrate(conn)
    return repo, conn


def _repo_b(tmp_path):
    repo = build_fixture_repo_b(tmp_path / "b")
    conn = connect(tmp_path / "b.db")
    migrate(conn)
    return repo, conn


def test_global_store_record_and_get_round_trip(tmp_path):
    repo_a, _conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    result = record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="SQLite beats Postgres for local-first single-user workloads.",
        assumptions="single-user, local-first",
    )

    memory = get_memory(global_conn, result["id"])
    assert memory["scope"] == "global"
    assert memory["assumptions"] == "single-user, local-first"
    assert memory["paths"] == []


def test_global_store_requires_nonempty_assumptions(tmp_path):
    """Proven live: a global lesson with no assumptions clears the §5.4
    gate vacuously and gets suggested in every context."""
    repo_a, _conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    with pytest.raises(ValidationError, match="require non-empty assumptions"):
        record_memory(
            global_conn, repo_a, type="lesson", scope="global", confidence="high",
            statement="x",
        )

    with pytest.raises(ValidationError, match="require non-empty assumptions"):
        record_memory(
            global_conn, repo_a, type="lesson", scope="global", confidence="high",
            statement="x", assumptions="   ",
        )


def test_global_store_rejects_linked_paths(tmp_path):
    repo_a, _conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    with pytest.raises(ValidationError, match="cannot have linked paths"):
        record_memory(
            global_conn, repo_a, type="lesson", scope="global", confidence="high",
            statement="x", assumptions="single-user", paths=["src/fixture_a/scanner.py"],
        )


def test_global_store_persists_across_separate_opens(tmp_path):
    repo_a, _conn_a = _repo_a(tmp_path)
    first_open = open_global_store()
    result = record_memory(
        first_open, repo_a, type="lesson", scope="global", confidence="high",
        statement="A durable global lesson.", assumptions="single-user",
    )
    first_open.close()

    second_open = open_global_store()
    memory = get_memory(second_open, result["id"])
    assert memory["statement"] == "A durable global lesson."


def test_cross_repo_retrieval_fires_only_on_assumption_match(tmp_path):
    """The Stage 8 exit criterion, verbatim: a lesson recorded while in
    fixture A is retrieved in fixture B when assumptions match, and NOT
    retrieved when they don't."""
    repo_a, local_conn_a = _repo_a(tmp_path)
    repo_b, local_conn_b = _repo_b(tmp_path)
    global_conn = open_global_store()

    record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="Prefer SQLite over Postgres for this kind of tool.",
        assumptions="single-user, local-first",
    )

    # matching context (fixture B, task states the same conditions)
    matching = retrieve_context(
        local_conn_b, repo_b,
        task="choosing a database for a single-user local-first tool",
        global_conn=global_conn,
    )
    assert matching["meta"]["matched"] == 1
    assert matching["data"][0]["statement"].startswith("Prefer SQLite")
    assert matching["data"][0]["scope"] == "global"

    # non-matching context (fixture B, task doesn't state the assumptions)
    non_matching = retrieve_context(
        local_conn_b, repo_b,
        task="choosing a database for a distributed multi-tenant service",
        global_conn=global_conn,
    )
    assert non_matching["meta"]["matched"] == 0


def test_repo_memories_never_leak_between_fixture_a_and_b(tmp_path):
    """The Stage 8 exit criterion, verbatim: repo memories never leak
    between fixture A and fixture B."""
    repo_a, local_conn_a = _repo_a(tmp_path)
    repo_b, local_conn_b = _repo_b(tmp_path)
    global_conn = open_global_store()

    record_memory(
        local_conn_a, repo_a, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at fifty items in fixture A.",
    )
    record_memory(
        local_conn_b, repo_b, type="decision", scope="repo", confidence="high",
        statement="Worker processes the queue one item at a time in fixture B.",
    )

    # A's local store never contains B's memory, and vice versa
    assert len(list_memories(local_conn_a)) == 1
    assert list_memories(local_conn_a)[0]["statement"].startswith("Scanner batches")
    assert len(list_memories(local_conn_b)) == 1
    assert list_memories(local_conn_b)[0]["statement"].startswith("Worker processes")

    # retrieving from B never surfaces A's repo-scoped memory, even with an
    # on-topic task and the global store consulted
    result = retrieve_context(
        local_conn_b, repo_b, task="scanner batches fifty items", global_conn=global_conn
    )
    assert result["meta"]["matched"] == 0

    # and the reverse
    result = retrieve_context(
        local_conn_a, repo_a, task="worker processes the queue", global_conn=global_conn
    )
    assert result["meta"]["matched"] == 0


def test_global_lesson_never_returned_without_global_conn(tmp_path):
    """Omitting global_conn (Stage 5-7 behavior) must not surface scope-B
    lessons at all -- confirms the dual-store merge is additive, not a
    silent behavior change for callers that don't opt in."""
    repo_a, _conn_a = _repo_a(tmp_path)
    repo_b, local_conn_b = _repo_b(tmp_path)
    global_conn = open_global_store()

    record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="Prefer SQLite over Postgres for this kind of tool.",
        assumptions="single-user, local-first",
    )

    result = retrieve_context(local_conn_b, repo_b, task="prefer SQLite over Postgres")
    assert result["meta"]["matched"] == 0


def test_search_surfaces_global_lessons_without_assumption_gate(tmp_path):
    """search is an explicit lookup, not a proactive suggestion -- unlike
    retrieve_context, it is not gated by assumptions (ARCHITECTURE.md's
    gate exists to keep unprompted suggestions conservative)."""
    repo_a, _conn_a = _repo_a(tmp_path)
    repo_b, local_conn_b = _repo_b(tmp_path)
    global_conn = open_global_store()

    record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="Prefer SQLite over Postgres for this kind of tool.",
        assumptions="single-user, local-first, low write concurrency",
    )

    # search from fixture B with a task that would FAIL the assumptions gate
    result = search_memory(
        local_conn_b, repo_b, query="SQLite Postgres", global_conn=global_conn
    )
    assert result["matched"] == 1
    assert result["data"][0]["scope"] == "global"


def test_find_memory_store_falls_back_to_global_when_absent_locally(tmp_path):
    repo_a, local_conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    # local store has nothing at all -- id 1 can only resolve via global
    global_result = record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="global lesson", assumptions="single-user",
    )

    assert find_memory_store(local_conn_a, global_conn, global_result["id"]) is global_conn

    with pytest.raises(NotFoundError):
        find_memory_store(local_conn_a, global_conn, 999999)


def test_find_memory_store_prefers_local_on_id_collision(tmp_path):
    """Both stores are independent autoincrement sequences and both start
    at 1, so the same id can legitimately refer to two different memories.
    Documented resolution order: local wins."""
    repo_a, local_conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    local_result = record_memory(
        local_conn_a, repo_a, type="fact", scope="repo", confidence="low", statement="local fact",
    )
    global_result = record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="global lesson", assumptions="single-user",
    )
    assert local_result["id"] == global_result["id"]  # the collision this test is about

    resolved = find_memory_store(local_conn_a, global_conn, local_result["id"])
    assert resolved is local_conn_a
    assert get_memory(resolved, local_result["id"])["statement"] == "local fact"


def test_find_memory_store_explicit_scope_reaches_the_shadowed_global_memory(tmp_path):
    """Proven live: without a disambiguator, a colliding local id 1 makes
    global id 1 completely unreachable by id. --scope='global' (surfaced in
    the CLI and, per Gate B follow-up, as an MCP tool input) is the fix."""
    repo_a, local_conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    local_result = record_memory(
        local_conn_a, repo_a, type="fact", scope="repo", confidence="low", statement="local fact",
    )
    global_result = record_memory(
        global_conn, repo_a, type="lesson", scope="global", confidence="high",
        statement="global lesson", assumptions="single-user",
    )
    assert local_result["id"] == global_result["id"]

    # default (no scope) still shadows the global one -- documented, not a bug
    assert find_memory_store(local_conn_a, global_conn, local_result["id"]) is local_conn_a

    # explicit scope reaches each one unambiguously
    local_store = find_memory_store(local_conn_a, global_conn, local_result["id"], scope="repo")
    global_store = find_memory_store(local_conn_a, global_conn, global_result["id"], scope="global")
    assert get_memory(local_store, local_result["id"])["statement"] == "local fact"
    assert get_memory(global_store, global_result["id"])["statement"] == "global lesson"


def test_find_memory_store_explicit_scope_raises_not_found_if_wrong(tmp_path):
    repo_a, local_conn_a = _repo_a(tmp_path)
    global_conn = open_global_store()

    local_result = record_memory(
        local_conn_a, repo_a, type="fact", scope="repo", confidence="low", statement="local fact",
    )

    with pytest.raises(NotFoundError):
        find_memory_store(local_conn_a, global_conn, local_result["id"], scope="global")
