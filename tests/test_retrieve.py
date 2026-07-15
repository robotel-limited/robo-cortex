import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.memory import record_memory
from robo_cortex.core.retrieve import WEIGHTS, retrieve_context

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_relevant_memory_ranks_above_unrelated_one(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="The scanner batches items in groups of fifty for the shared host.",
    )
    record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The health check endpoint returns ok with no side effects.",
    )

    result = retrieve_context(conn, repo, task="why does the scanner use batches of fifty")

    assert result["meta"]["matched"] == 1
    assert result["data"][0]["statement"].startswith("The scanner batches")


def test_no_match_returns_honest_empty_pack(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="completely unrelated statement about nothing in particular",
    )

    result = retrieve_context(conn, repo, task="xyzzy nonexistent keyword plugh")

    assert result == {
        "data": [],
        "meta": {"matched": 0, "returned": 0, "omitted": [], "needs_review": 0, "contradicted": 0},
    }


def test_budget_items_never_exceeded_and_reports_truncation(tmp_path):
    repo, conn = _store(tmp_path)
    for i in range(20):
        record_memory(
            conn, repo, type="fact", scope="repo", confidence="low",
            statement=f"scanner detail number {i} about batching behavior",
        )

    result = retrieve_context(conn, repo, task="scanner batching behavior", budget_items=15)

    assert result["meta"]["matched"] == 20
    assert result["meta"]["returned"] == 15
    assert len(result["data"]) == 15
    assert result["meta"]["omitted"] == [{"reason": "budget", "count": 5}]


def test_budget_tokens_never_exceeded_and_reports_truncation(tmp_path):
    repo, conn = _store(tmp_path)
    long_statement = "scanner batching " + ("word " * 30)  # comfortably under the 500-char cap
    for i in range(10):
        record_memory(
            conn, repo, type="fact", scope="repo", confidence="low",
            statement=f"{long_statement} variant {i}",
        )

    result = retrieve_context(conn, repo, task="scanner batching", budget_tokens=150, budget_items=15)

    assert result["meta"]["matched"] == 10
    assert result["meta"]["returned"] < 10
    assert result["meta"]["omitted"][0]["reason"] == "budget"
    assert result["meta"]["omitted"][0]["count"] == 10 - result["meta"]["returned"]


def test_explain_components_sum_to_total_score(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at fifty items because of host timeouts.",
        paths=["src/fixture_a/scanner.py"],
    )

    result = retrieve_context(
        conn, repo, task="scanner batches", paths=["src/fixture_a/scanner.py"], explain=True
    )

    item = result["data"][0]
    components = item["score_breakdown"]
    recomputed = sum(WEIGHTS[key] * components[key] for key in WEIGHTS)
    assert abs(recomputed - components["total"]) < 1e-9
    assert abs(item["score"] - components["total"]) < 1e-9


def test_excluded_statuses_never_returned(tmp_path):
    repo, conn = _store(tmp_path)
    ids = []
    for status in ("superseded", "invalidated", "abandoned", "archived"):
        result = record_memory(
            conn, repo, type="fact", scope="repo", confidence="low",
            statement=f"scanner batching fact that is {status}",
        )
        ids.append(result["id"])
        conn.execute("UPDATE memory SET status = ? WHERE id = ?", (status, result["id"]))
    active_result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="scanner batching fact that is still active",
    )

    result = retrieve_context(conn, repo, task="scanner batching fact")

    returned_ids = {item["id"] for item in result["data"]}
    assert returned_ids == {active_result["id"]}
    assert result["meta"]["matched"] == 1


def test_needs_review_and_contradicted_counts_are_exact(tmp_path):
    repo, conn = _store(tmp_path)
    flagged = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="scanner batching fact needing review",
    )
    conn.execute(
        "UPDATE memory SET status = 'needs_review', status_reason = 'test' WHERE id = ?",
        (flagged["id"],),
    )
    contradicted_a = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="scanner batching fact version A",
    )
    contradicted_b = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="scanner batching fact version B",
    )
    conn.execute(
        "INSERT INTO memory_link (from_id, to_id, link_type) VALUES (?, ?, 'contradicts')",
        (contradicted_a["id"], contradicted_b["id"]),
    )
    record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="scanner batching fact, no issues",
    )

    result = retrieve_context(conn, repo, task="scanner batching fact")

    assert result["meta"]["matched"] == 4
    assert result["meta"]["returned"] == 4
    assert result["meta"]["needs_review"] == 1
    assert result["meta"]["contradicted"] == 2


def test_global_scope_memories_not_yet_returned(tmp_path):
    """Scope-B consultation lands in Stage 8; Stage 5 is scope='repo' only."""
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="lesson", scope="global", confidence="high",
        statement="scanner batching lesson that should not surface yet",
        assumptions="single-user",
    )

    result = retrieve_context(conn, repo, task="scanner batching lesson")

    assert result["meta"]["matched"] == 0


def test_task_with_fts_special_characters_does_not_crash(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="lesson", scope="repo", confidence="high",
        statement="SQLite is preferred for single-user local-first workloads",
    )

    result = retrieve_context(conn, repo, task="why single-user local-first: SQLite?")

    assert result["meta"]["matched"] == 1


def test_token_budget_counts_evidence_summaries(tmp_path):
    """§5.2: the token estimate covers "the full rendered item including
    evidence summaries" -- not just the statement. A memory with a short
    statement but a long evidence description must count the whole thing."""
    from robo_cortex.core.evidence import attach_evidence

    repo, conn = _store(tmp_path)
    short = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="scanner batching short",
    )
    attach_evidence(
        conn, repo, short["id"], kind="free_text",
        description="scanner batching " + ("padding word " * 30),  # long evidence text, <=500 chars
    )

    result = retrieve_context(conn, repo, task="scanner batching", budget_tokens=2000, explain=True)

    # statement alone is ~24 chars (~6 tokens); with evidence description
    # included it should be several hundred tokens -- confirm it actually
    # grew, i.e. evidence text was counted, not silently dropped from the
    # rendered/estimated size.
    pack_item = result["data"][0]
    assert pack_item["id"] == short["id"]
    # tight budget that the statement alone would fit under, but not with
    # evidence included -- proves evidence text is part of what's counted.
    tight_result = retrieve_context(conn, repo, task="scanner batching", budget_tokens=20)
    assert tight_result["meta"]["returned"] == 0
    assert tight_result["meta"]["omitted"] == [{"reason": "budget", "count": 1}]


def test_explain_memory_score_matches_retrieve_context_for_same_task(tmp_path):
    """show --explain-against and retrieve --explain must never disagree
    for the same memory+task pair -- both go through the same scoring path."""
    from robo_cortex.core.retrieve import explain_memory_score

    # explain_memory_score never takes task paths (matches MCP_TOOLS.md's
    # get_memory contract, which has no paths field) -- so the retrieve_context
    # call it's compared against must also omit paths, for an apples-to-apples
    # check. path_overlap is 0 in both, which is the honest comparable state.
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at fifty items because of host timeouts.",
        paths=["src/fixture_a/scanner.py"],
    )

    pack = retrieve_context(conn, repo, task="scanner batches fifty", explain=True)
    pack_components = pack["data"][0]["score_breakdown"]

    explained = explain_memory_score(conn, result["id"], "scanner batches fifty")

    # recency is computed from datetime.now() at each call, microseconds
    # apart between the two calls in this test -- approx, not exact, equality
    # is the correct check (the scoring *path* is identical; wall-clock isn't).
    assert explained.keys() == pack_components.keys()
    for key in explained:
        assert explained[key] == pytest.approx(pack_components[key], abs=1e-6)


def test_explain_memory_score_zero_text_match_when_task_does_not_match(tmp_path):
    from robo_cortex.core.retrieve import explain_memory_score

    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="high",
        statement="Completely unrelated statement about nothing in particular.",
    )

    components = explain_memory_score(conn, result["id"], "xyzzy nonexistent keyword plugh")

    assert components["text_match"] == 0.0


def test_retrieve_does_not_crash_on_readonly_database(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="lesson", scope="repo", confidence="high",
        statement="Use async-await for concurrent operations.",
    )
    conn.close()

    db_path = tmp_path / "memory.db"
    db_path.chmod(0o444)

    try:
        ro_conn = connect(db_path)
        result = retrieve_context(ro_conn, repo, task="async await")

        assert result["meta"]["returned"] == 1
        ro_conn.close()
    finally:
        db_path.chmod(0o644)
