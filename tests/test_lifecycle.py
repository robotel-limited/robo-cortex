import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.errors import IllegalTransitionError, NotFoundError, ValidationError
from robo_cortex.core.lifecycle import change_status, create_link
from robo_cortex.core.memory import get_memory, record_memory

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def _record(repo, conn, **overrides):
    fields = dict(type="fact", scope="repo", statement="a fact", confidence="low")
    fields.update(overrides)
    return record_memory(conn, repo, **fields)["id"]


def test_legal_transition_supersede_requires_target(tmp_path):
    repo, conn = _store(tmp_path)
    old_id = _record(repo, conn, statement="old fact")
    new_id = _record(repo, conn, statement="new fact")
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (old_id,))

    with pytest.raises(ValidationError, match="supersedes_link_to"):
        change_status(conn, repo, old_id, "superseded", "replaced", supersedes_link_to=None)

    result = change_status(conn, repo, old_id, "superseded", "replaced by newer fact", supersedes_link_to=new_id)
    assert result["status"] == "superseded"
    memory = get_memory(conn, old_id)
    assert memory["status"] == "superseded"
    assert {"link_type": "supersedes", "memory_id": new_id, "direction": "outgoing"} in memory["links"]


def test_illegal_transition_rejected(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn)
    conn.execute("UPDATE memory SET status = 'archived' WHERE id = ?", (memory_id,))

    with pytest.raises(IllegalTransitionError, match="archived"):
        change_status(conn, repo, memory_id, "active", "trying to revive a terminal memory")


def test_reason_is_required(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn)

    with pytest.raises(ValidationError, match="reason"):
        change_status(conn, repo, memory_id, "abandoned", "")


def test_abandon_then_archive_matches_matrix(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn, type="experiment")

    change_status(conn, repo, memory_id, "abandoned", "streaming approach doubled memory use")
    assert get_memory(conn, memory_id)["status"] == "abandoned"

    change_status(conn, repo, memory_id, "archived", "compressed into a lesson")
    assert get_memory(conn, memory_id)["status"] == "archived"

    with pytest.raises(IllegalTransitionError):
        change_status(conn, repo, memory_id, "active", "trying to un-archive")


def test_active_can_be_abandoned(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn, type="experiment")
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (memory_id,))

    result = change_status(conn, repo, memory_id, "abandoned", "measured 2.4x slower, not faster")

    assert result["status"] == "abandoned"
    assert get_memory(conn, memory_id)["status"] == "abandoned"


def test_evidence_then_abandon_real_dead_end(tmp_path):
    """Regression: attach_evidence auto-promotes provisional -> active on
    first evidence (evidence.py), which used to make active -> abandoned
    illegal -- forbidding exactly the natural order of "record the finding
    that proves it's a dead end, then abandon it." See ARCHITECTURE.md §4."""
    from robo_cortex.core.evidence import attach_evidence

    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn, type="experiment", statement="tried a redis cache for reads")

    attach_evidence(
        conn,
        repo,
        memory_id,
        kind="test_output",
        description="benchmark: cached 0.195ms/call vs uncached 0.080ms/call, 2.4x slower",
    )
    assert get_memory(conn, memory_id)["status"] == "active"  # auto-promoted on first evidence

    result = change_status(conn, repo, memory_id, "abandoned", "caching made it slower, not faster")
    assert result["status"] == "abandoned"


def test_manual_needs_review_is_not_auto_healed(tmp_path):
    """A memory flagged needs_review by change_status (not by the git-hash
    mechanism) must not be silently reverted just because its paths (if any)
    happen to already be consistent -- see invalidate.py's pre_review_status
    gate, fixed specifically for this."""
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn, confidence="low")
    conn.execute("UPDATE memory SET status = 'active' WHERE id = ?", (memory_id,))

    change_status(conn, repo, memory_id, "needs_review", "confidence seems overstated, please double check")

    from robo_cortex.core.invalidate import refresh_staleness
    refresh_staleness(conn, repo)

    memory = get_memory(conn, memory_id)
    assert memory["status"] == "needs_review"
    assert memory["status_reason"] == "confidence seems overstated, please double check"


def test_manual_activate_clears_needs_review(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn)
    conn.execute("UPDATE memory SET status = 'needs_review' WHERE id = ?", (memory_id,))

    result = change_status(conn, repo, memory_id, "active", "manually re-verified, looks fine")

    assert result["status"] == "active"
    assert get_memory(conn, memory_id)["status_reason"] == "manually re-verified, looks fine"


def test_create_link_contradicts_both_visible(tmp_path):
    repo, conn = _store(tmp_path)
    a = _record(repo, conn, statement="X is true")
    b = _record(repo, conn, statement="X is false")

    create_link(conn, a, b, "contradicts")

    memory_a = get_memory(conn, a)
    memory_b = get_memory(conn, b)
    assert {"link_type": "contradicts", "memory_id": b, "direction": "outgoing"} in memory_a["links"]
    assert {"link_type": "contradicts", "memory_id": a, "direction": "incoming"} in memory_b["links"]


def test_create_link_rejects_self_link(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn)
    with pytest.raises(ValidationError, match="itself"):
        create_link(conn, memory_id, memory_id, "contradicts")


def test_create_link_rejects_unknown_memory(tmp_path):
    repo, conn = _store(tmp_path)
    memory_id = _record(repo, conn)
    with pytest.raises(NotFoundError):
        create_link(conn, memory_id, 9999, "contradicts")


def test_create_link_rejects_duplicate_identical_link(tmp_path):
    repo, conn = _store(tmp_path)
    a = _record(repo, conn, statement="A")
    b = _record(repo, conn, statement="B")
    create_link(conn, a, b, "contradicts")

    with pytest.raises(ValidationError, match="already exists"):
        create_link(conn, a, b, "contradicts")


def test_contradiction_resolved_only_by_supersession(tmp_path):
    repo, conn = _store(tmp_path)
    a = _record(repo, conn, statement="batch size is 50")
    b = _record(repo, conn, statement="batch size is 100")
    conn.execute("UPDATE memory SET status = 'active' WHERE id IN (?, ?)", (a, b))
    create_link(conn, a, b, "contradicts")

    # both still fully visible before resolution
    assert get_memory(conn, a)["status"] == "active"
    assert get_memory(conn, b)["status"] == "active"

    change_status(conn, repo, a, "superseded", "confirmed 100 is correct", supersedes_link_to=b)

    memory_a = get_memory(conn, a)
    assert memory_a["status"] == "superseded"
    link_types = {link["link_type"] for link in memory_a["links"]}
    assert "contradicts" in link_types  # never deleted, only joined by a supersedes link
    assert "supersedes" in link_types
