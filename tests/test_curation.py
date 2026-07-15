from robo_cortex.core.db import connect, migrate
from robo_cortex.core.lifecycle import change_status
from robo_cortex.core.memory import get_memory, list_memories, record_memory

from .fixtures import build_fixture_repo_a


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_near_duplicate_statement_flags_for_consolidation(tmp_path):
    repo, conn = _store(tmp_path)
    first = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches items in groups of fifty for the shared host.",
    )
    second = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches items in groups of fifty for shared hosts.",
    )

    flagged = list_memories(conn, needs_consolidation=True)
    flagged_ids = {m["id"] for m in flagged}
    assert flagged_ids == {first["id"], second["id"]}

    memory = get_memory(conn, second["id"])
    assert any(link["link_type"] == "duplicate_of" for link in memory["links"])


def test_unrelated_memories_never_flagged_as_duplicates(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="Scanner batches items in groups of fifty.",
    )
    record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="Health check endpoint returns ok with no side effects.",
    )

    assert list_memories(conn, needs_consolidation=True) == []


def test_duplicates_are_flagged_never_auto_merged(tmp_path):
    repo, conn = _store(tmp_path)
    first = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="CSV export uses a semicolon delimiter for compatibility.",
    )
    second = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="CSV export uses a semicolon delimiter for compatibility reasons.",
    )

    # both rows still independently exist, unmodified statements
    assert get_memory(conn, first["id"])["statement"] == "CSV export uses a semicolon delimiter for compatibility."
    assert get_memory(conn, second["id"])["statement"] == "CSV export uses a semicolon delimiter for compatibility reasons."


def test_dead_end_compression_lesson_retrievable_cold_storage_not_in_pack(tmp_path):
    repo, conn = _store(tmp_path)
    experiment = record_memory(
        conn, repo, type="experiment", scope="repo", confidence="medium",
        statement="Tried streaming the CSV export to cut memory use.",
    )
    change_status(
        conn, repo, experiment["id"], "abandoned",
        "Streaming doubled memory use under load due to buffering; reverted.",
    )

    lesson = record_memory(
        conn, repo, type="lesson", scope="repo", confidence="high",
        statement="Do not stream the CSV export; it doubles memory use under load.",
        lesson_from=experiment["id"],
    )
    from robo_cortex.core.evidence import attach_evidence
    attach_evidence(
        conn, repo, lesson["id"], kind="cold_storage_ref",
        description="full streaming experiment log and memory profiler output",
        cold_storage_content="=== full verbose experiment transcript ===\n" * 20,
    )

    # lesson is retrievable
    lesson_memory = get_memory(conn, lesson["id"])
    assert lesson_memory["status"] == "active"  # promoted by attach_evidence
    assert any(link["link_type"] == "lesson_from" for link in lesson_memory["links"])

    # abandoned experiment excluded from default retrieval-eligible statuses
    experiment_memory = get_memory(conn, experiment["id"])
    assert experiment_memory["status"] == "abandoned"

    # cold storage content is not in the FTS index (not in normal packs)
    row = conn.execute(
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'transcript'"
    ).fetchone()
    assert row[0] == 0


def test_abandoned_without_lesson_is_queryable(tmp_path):
    repo, conn = _store(tmp_path)
    forgotten = record_memory(
        conn, repo, type="experiment", scope="repo", confidence="low",
        statement="Tried a caching layer that was never followed up on.",
    )
    change_status(conn, repo, forgotten["id"], "abandoned", "ran out of time, no lesson written yet")

    compressed = record_memory(
        conn, repo, type="experiment", scope="repo", confidence="low",
        statement="Tried a retry queue that made latency worse.",
    )
    change_status(conn, repo, compressed["id"], "abandoned", "retries amplified load")
    record_memory(
        conn, repo, type="lesson", scope="repo", confidence="high",
        statement="Do not add a retry queue here; it amplifies load under failure.",
        lesson_from=compressed["id"],
    )

    gap = list_memories(conn, abandoned_without_lesson=True)
    gap_ids = {m["id"] for m in gap}
    assert gap_ids == {forgotten["id"]}
