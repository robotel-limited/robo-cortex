import json

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.memory import list_memories, record_batch

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def _line(**fields) -> str:
    return json.dumps(fields)


def test_batch_records_all_valid_lines(tmp_path):
    repo, conn = _store(tmp_path)
    lines = [
        _line(type="fact", scope="repo", statement="fact one", confidence="low"),
        _line(type="decision", scope="repo", statement="decision one", confidence="high"),
        _line(type="hypothesis", scope="repo", statement="hypothesis one", confidence="medium"),
    ]

    result = record_batch(conn, repo, lines)

    assert result["created"] == 3
    assert result["failed"] == []
    assert len(list_memories(conn)) == 3


def test_batch_rejects_scope_global_lines(tmp_path):
    """Stage 8: scope='global' memories live in ~/.cortex/global.db, not
    whichever local store record_batch was given -- a batch line requesting
    it is a clear per-line failure, not a silent write to the wrong file."""
    repo, conn = _store(tmp_path)
    lines = [
        _line(type="fact", scope="repo", statement="fact one", confidence="low"),
        _line(type="lesson", scope="global", statement="a reusable lesson", confidence="medium"),
    ]

    result = record_batch(conn, repo, lines)

    assert result["created"] == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["line"] == 2
    assert "scope='global' is not supported in --batch" in result["failed"][0]["error"]
    assert len(list_memories(conn)) == 1


def test_batch_reports_each_invalid_line_and_still_records_valid_ones(tmp_path):
    repo, conn = _store(tmp_path)
    lines = [
        _line(type="fact", scope="repo", statement="good line one", confidence="low"),
        _line(type="fact", scope="repo", statement="x" * 501, confidence="low"),  # too long
        "not even json",
        _line(type="fact", scope="repo", statement="dead path", confidence="low",
              paths=["does/not/exist.py"]),
        _line(type="fact", scope="repo", statement="good line two", confidence="high"),
    ]

    result = record_batch(conn, repo, lines)

    assert result["created"] == 2
    assert len(result["failed"]) == 3
    assert result["failed"][0]["line"] == 2
    assert "exceeds 500" in result["failed"][0]["error"]
    assert result["failed"][1]["line"] == 3
    assert "invalid JSON" in result["failed"][1]["error"]
    assert result["failed"][2]["line"] == 4
    assert "does not exist at HEAD" in result["failed"][2]["error"]
    assert "Commit the file first" in result["failed"][2]["error"]

    recorded = list_memories(conn)
    assert len(recorded) == 2
    assert {m["statement"] for m in recorded} == {"good line one", "good line two"}


def test_batch_bad_line_never_partially_records(tmp_path):
    repo, conn = _store(tmp_path)
    # one path valid, one path dead -- the whole line must be rejected, not
    # left half-written with only the memory row or only one path row.
    lines = [
        _line(
            type="decision", scope="repo", statement="partially valid paths",
            confidence="high",
            paths=["src/fixture_a/scanner.py", "src/fixture_a/does_not_exist.py"],
        )
    ]

    result = record_batch(conn, repo, lines)

    assert result["created"] == 0
    assert len(result["failed"]) == 1
    assert list_memories(conn) == []
    assert conn.execute("SELECT count(*) FROM memory_path").fetchone()[0] == 0


def test_batch_ignores_blank_lines(tmp_path):
    repo, conn = _store(tmp_path)
    lines = ["", "   ", _line(type="fact", scope="repo", statement="one", confidence="low"), ""]

    result = record_batch(conn, repo, lines)

    assert result["created"] == 1
    assert result["failed"] == []
