import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.errors import NotFoundError, ValidationError
from robo_cortex.core.evidence import attach_evidence, evidence_strength, verify_evidence
from robo_cortex.core.memory import get_memory, record_memory

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_attach_evidence_promotes_provisional_to_active(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="low")
    assert get_memory(conn, result["id"])["status"] == "provisional"

    attach_evidence(
        conn, repo, result["id"], kind="test_output",
        description="pytest run failed with TimeoutError at batch_size=200",
        command="pytest tests/test_scanner.py -k timeout",
        expected_outcome="fails with TimeoutError",
    )

    assert get_memory(conn, result["id"])["status"] == "active"


def test_attach_evidence_does_not_touch_already_active(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="low")
    conn.execute("UPDATE memory SET status = 'needs_review' WHERE id = ?", (result["id"],))

    attach_evidence(conn, repo, result["id"], kind="free_text", description="still true, checked")

    assert get_memory(conn, result["id"])["status"] == "needs_review"  # unrelated to evidence


def test_attach_evidence_rejects_unknown_memory(tmp_path):
    repo, conn = _store(tmp_path)
    with pytest.raises(NotFoundError):
        attach_evidence(conn, repo, 9999, kind="free_text", description="x")


def test_attach_evidence_validates_kind_and_description(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="low")
    with pytest.raises(ValidationError, match="invalid kind"):
        attach_evidence(conn, repo, result["id"], kind="nonsense", description="x")
    with pytest.raises(ValidationError, match="must not be empty"):
        attach_evidence(conn, repo, result["id"], kind="free_text", description="  ")
    with pytest.raises(ValidationError, match="exceeds 500"):
        attach_evidence(conn, repo, result["id"], kind="free_text", description="x" * 501)


def test_evidence_strength_mechanical_not_judged(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="low")

    assert evidence_strength(conn, result["id"]) == 0.0

    attach_evidence(conn, repo, result["id"], kind="free_text", description="a note")
    assert evidence_strength(conn, result["id"]) == 0.4

    attach_evidence(conn, repo, result["id"], kind="test_output", description="a real test run",
                     command="pytest -k x", expected_outcome="passes")
    # base = max(0.4, 1.0) + 0.1 * (2-1) = 1.0 + 0.1, capped at 1.0
    assert evidence_strength(conn, result["id"]) == 1.0


def test_cold_storage_ref_stores_and_links_verbose_content(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="lesson", scope="repo", statement="x", confidence="medium")

    attach_evidence(
        conn, repo, result["id"], kind="cold_storage_ref",
        description="full experiment log from the streaming attempt",
        cold_storage_content="verbose multi-paragraph log content that would never fit in a pack" * 10,
    )

    memory = get_memory(conn, result["id"])
    evidence = memory["evidence"][0]
    assert evidence["kind"] == "cold_storage_ref"
    assert evidence["ref"] is not None
    assert "verbose multi-paragraph log" in evidence["cold_storage_content"]

    # not in the FTS index / normal search surface
    row = conn.execute(
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'verbose'"
    ).fetchone()
    assert row[0] == 0


def test_verify_evidence_command_backed_returns_command_unchanged(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="low")
    attach = attach_evidence(
        conn, repo, result["id"], kind="test_output", description="ran it",
        command="pytest -k batch_size", expected_outcome="fails at 200",
    )

    verified = verify_evidence(conn, attach["evidence_id"])

    assert verified["command"] == "pytest -k batch_size"
    assert verified["expected_outcome"] == "fails at 200"
    assert "data" in verified["note"].lower() or "review" in verified["note"].lower()


def test_verify_evidence_gitea_backed_degrades_to_unverifiable_when_unconfigured(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(conn, repo, type="decision", scope="repo", statement="x", confidence="high")
    attach = attach_evidence(
        conn, repo, result["id"], kind="gitea_pr", description="fixed in PR", ref="pr:88",
    )

    verified = verify_evidence(conn, attach["evidence_id"])

    assert verified["status"] == "unverifiable"
    assert verified["reason"] == "gitea_not_configured"

    memory = get_memory(conn, result["id"])
    assert memory["evidence"][0]["status"] == "unverifiable"
    assert memory["evidence"][0]["description"] == "fixed in PR"  # rots to unverifiable, not nonsense


def test_verify_evidence_rejects_unknown_id(tmp_path):
    _repo, conn = _store(tmp_path)
    with pytest.raises(NotFoundError):
        verify_evidence(conn, 9999)
