from robo_cortex.core.db import connect, migrate
from robo_cortex.core.memory import get_memory, record_memory
from robo_cortex.core.retrieve import search_memory

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_search_finds_matches_across_more_than_budget(tmp_path):
    repo, conn = _store(tmp_path)
    for i in range(20):
        record_memory(
            conn, repo, type="fact", scope="repo", confidence="low",
            statement=f"scanner batching detail number {i}",
        )

    result = search_memory(conn, repo, query="scanner batching")

    assert result["matched"] == 20
    assert result["returned"] == 20  # no budget truncation, just a plain limit


def test_search_respects_limit(tmp_path):
    repo, conn = _store(tmp_path)
    for i in range(10):
        record_memory(
            conn, repo, type="fact", scope="repo", confidence="low",
            statement=f"scanner batching detail number {i}",
        )

    result = search_memory(conn, repo, query="scanner batching", limit=3)

    assert result["returned"] == 3


def test_search_filters_by_type_scope_status(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(conn, repo, type="fact", scope="repo", confidence="low", statement="scanner fact")
    record_memory(conn, repo, type="decision", scope="repo", confidence="high", statement="scanner decision")

    result = search_memory(conn, repo, query="scanner", type="decision")

    assert result["returned"] == 1
    assert result["data"][0]["type"] == "decision"


def test_search_is_a_lazy_check_trigger_point(tmp_path):
    """search must actually call refresh_staleness, not just claim to --
    the exact class of bug affected() had (Stage 6)."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    from .fixtures import run_git
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "edit scanner")

    search_memory(conn, repo, query="scanner batches")

    assert get_memory(conn, result["id"])["status"] == "needs_review"
