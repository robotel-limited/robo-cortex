import subprocess

import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.errors import NotFoundError, ValidationError
from robo_cortex.core.memory import get_memory, list_memories, record_memory

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_record_then_show_round_trip(tmp_path):
    repo, conn = _store(tmp_path)

    result = record_memory(
        conn,
        repo,
        type="decision",
        scope="repo",
        statement="Scanner batches at 50 items because larger batches time out.",
        confidence="high",
        why_it_matters="Prevents future re-litigation of the batch size.",
        paths=["src/fixture_a/scanner.py"],
    )

    fetched = get_memory(conn, result["id"])
    assert fetched["type"] == "decision"
    assert fetched["scope"] == "repo"
    assert fetched["status"] == "provisional"
    assert fetched["confidence"] == "high"
    assert fetched["statement"].startswith("Scanner batches at 50")
    assert fetched["paths"] == [
        {"path": "src/fixture_a/scanner.py", "blob_hash": result["paths"][0]["blob_hash"]}
    ]


def test_show_unknown_id_raises_not_found(tmp_path):
    _repo, conn = _store(tmp_path)
    with pytest.raises(NotFoundError):
        get_memory(conn, 999)


def test_record_refuses_nonexistent_path(tmp_path):
    repo, conn = _store(tmp_path)

    with pytest.raises(ValidationError, match="does not exist at HEAD"):
        record_memory(
            conn,
            repo,
            type="fact",
            scope="repo",
            statement="This links to a path that was never committed.",
            confidence="low",
            paths=["src/fixture_a/does_not_exist.py"],
        )

    # the dead link must not leave a partially-created memory behind
    assert list_memories(conn) == []


def test_record_refuses_over_length_statement(tmp_path):
    repo, conn = _store(tmp_path)

    with pytest.raises(ValidationError, match="exceeds 500 characters"):
        record_memory(
            conn,
            repo,
            type="fact",
            scope="repo",
            statement="x" * 501,
            confidence="low",
        )
    assert list_memories(conn) == []


def test_record_refuses_empty_statement(tmp_path):
    repo, conn = _store(tmp_path)
    with pytest.raises(ValidationError, match="must not be empty"):
        record_memory(conn, repo, type="fact", scope="repo", statement="   ", confidence="low")


def test_record_refuses_assumptions_on_repo_scope(tmp_path):
    repo, conn = _store(tmp_path)
    with pytest.raises(ValidationError, match="scope='global'"):
        record_memory(
            conn, repo, type="lesson", scope="repo", statement="x",
            confidence="low", assumptions="single-user",
        )


def test_record_refuses_invalid_type_scope_confidence(tmp_path):
    repo, conn = _store(tmp_path)
    with pytest.raises(ValidationError, match="invalid type"):
        record_memory(conn, repo, type="nonsense", scope="repo", statement="x", confidence="low")
    with pytest.raises(ValidationError, match="invalid scope"):
        record_memory(conn, repo, type="fact", scope="nonsense", statement="x", confidence="low")
    with pytest.raises(ValidationError, match="invalid confidence"):
        record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="nonsense")


def test_blob_hash_matches_git_rev_parse(tmp_path):
    repo, conn = _store(tmp_path)

    result = record_memory(
        conn, repo, type="fact", scope="repo",
        statement="The exporter joins rows with a semicolon.",
        confidence="medium", paths=["src/fixture_a/exporter.py"],
    )

    expected = subprocess.run(
        ["git", "rev-parse", "HEAD:src/fixture_a/exporter.py"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    assert result["paths"][0]["blob_hash"] == expected


def test_list_memories_filters(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(conn, repo, type="fact", scope="repo", statement="a fact", confidence="low")
    record_memory(conn, repo, type="decision", scope="repo", statement="a decision", confidence="high")
    record_memory(
        conn, repo, type="lesson", scope="global", statement="a lesson", confidence="medium",
        assumptions="single-user",
    )

    assert len(list_memories(conn)) == 3
    assert len(list_memories(conn, type="fact")) == 1
    assert len(list_memories(conn, scope="global")) == 1
    assert len(list_memories(conn, status="provisional")) == 3
    assert list_memories(conn, status="active") == []
