"""Python SDK: in-process, no subprocess involved.

Per raport-oportunitate.md's audit, the pre-0.3.0 SDK was a subprocess
wrapper that (a) called `search()` with the wrong argument shape, (b) had
no `assumptions` parameter so scope='global' was unreachable, and (c)
swallowed every exception into an {"error": ...} dict nothing checked for.
These tests pin the rewritten in-process behavior: errors propagate as
real RoboCortexError subclasses, and every documented use case (including
scope='global') actually works.
"""

import pytest

from robo_cortex.core.errors import NotFoundError, NotInitializedError, ValidationError
from robo_cortex.core.init import init_repo
from robo_cortex.sdk import RoboCortex, record, retrieve, search

from .fixtures import build_fixture_repo_a


def _init(repo):
    init_repo(str(repo))


def test_record_then_get_memory_round_trip(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    result = cortex.record(
        type="fact", statement="SDK round trip fact", scope="repo", confidence="high",
    )
    assert result["status"] == "provisional"

    fetched = cortex.get_memory(result["id"])
    assert fetched["statement"] == "SDK round trip fact"
    assert fetched["type"] == "fact"
    assert fetched["confidence"] == "high"


def test_record_then_retrieve_finds_it(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    cortex.record(
        type="lesson", statement="clipboard writeText fails on HTTP contexts",
        scope="repo", confidence="high",
    )

    result = cortex.retrieve("clipboard http")
    assert result["meta"]["matched"] >= 1
    assert any("clipboard" in item["statement"] for item in result["data"])


def test_record_scope_global_requires_and_accepts_assumptions(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    # Without assumptions: rejected, same as `record_memory` and `roco record`.
    with pytest.raises(ValidationError):
        cortex.record(
            type="lesson", statement="global lesson missing assumptions",
            scope="global", confidence="high",
        )

    # With assumptions: succeeds -- this was unreachable through the old
    # subprocess SDK (no assumptions parameter existed at all).
    result = cortex.record(
        type="lesson", statement="global lesson with assumptions",
        scope="global", confidence="high",
        assumptions="local-first, single-user",
    )
    assert result["status"] == "provisional"

    fetched = cortex.get_memory(result["id"], scope="global")
    assert fetched["scope"] == "global"
    assert fetched["assumptions"] == "local-first, single-user"


def test_search_returns_matches(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    cortex.record(type="fact", statement="scanner batches at 50 items", scope="repo", confidence="high")
    cortex.record(type="fact", statement="unrelated statement about exports", scope="repo", confidence="low")

    result = cortex.search("scanner batches")
    assert result["matched"] >= 1
    assert any("scanner" in item["statement"] for item in result["data"])


def test_search_respects_limit(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    for i in range(5):
        cortex.record(type="fact", statement=f"limit test statement number {i}", scope="repo", confidence="low")

    result = cortex.search("limit test statement", limit=2)
    assert result["returned"] <= 2


def test_list_memories_merges_repo_and_global(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    cortex.record(type="fact", statement="repo scoped item", scope="repo", confidence="low")
    cortex.record(
        type="lesson", statement="global scoped item", scope="global",
        confidence="low", assumptions="always applies",
    )

    all_memories = cortex.list_memories()
    statements = {m["statement"] for m in all_memories}
    assert "repo scoped item" in statements
    assert "global scoped item" in statements

    repo_only = cortex.list_memories(scope="repo")
    assert all(m["scope"] == "repo" for m in repo_only)


def test_get_memory_unknown_id_raises_not_found(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    with pytest.raises(NotFoundError):
        cortex.get_memory(99999)


def test_retrieve_on_uninitialized_repo_raises_not_initialized(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    # deliberately skip _init(repo)
    cortex = RoboCortex(str(repo))

    with pytest.raises(NotInitializedError):
        cortex.retrieve("anything")


def test_record_dead_path_raises_validation_error(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    cortex = RoboCortex(str(repo))

    with pytest.raises(ValidationError):
        cortex.record(
            type="fact", statement="linked to a path that doesn't exist",
            scope="repo", confidence="low", paths=["does/not/exist.py"],
        )


def test_module_level_convenience_functions(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = record(
        type="fact", statement="convenience function record", repo_path=str(repo),
        scope="repo", confidence="medium",
    )
    assert result["status"] == "provisional"

    found = retrieve("convenience function record", repo_path=str(repo))
    assert found["meta"]["matched"] >= 1

    searched = search("convenience function", repo_path=str(repo))
    assert searched["matched"] >= 1
