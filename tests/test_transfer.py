"""Export/import/merge: CLI-contract tests (stable across internal refactors)
and core-level tests for merge_jsonl/export_memories (stable signatures).

Per raport-oportunitate.md (2026-07-14 audit) and plan-reinforcement.md
Etapa 1: these tests define "reparat" for the transfer bug-fix work in
Etapa 2/3. Tests reproducing today's known bugs are marked
xfail(strict=True) -- they must start passing exactly when the
corresponding fix lands, and strict=True turns an accidental early fix
(or a regression back to broken) into a hard test failure either way.
"""

import json
import subprocess
import sys

import pytest

from robo_cortex.core.transfer import export_memories, merge_jsonl
from robo_cortex.core.db import connect, migrate

from .fixtures import build_fixture_repo_a, run_git


def _run_cli(*args, cwd=None, input=None):
    return subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
    )


def _init(repo):
    result = _run_cli("init", "--repo", str(repo))
    assert result.returncode == 0, result.stderr


def _record(repo, statement="a fact", type="fact", scope="repo", confidence="low", extra=None):
    args = [
        "record", "--repo", str(repo), "--type", type, "--scope", scope,
        "--statement", statement, "--confidence", confidence, "--json",
    ]
    if extra:
        args += extra
    result = _run_cli(*args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["id"]


# ---------------------------------------------------------------------------
# Etapa 1 case 1: import with scope=repo crashes (tuple returned by _store()
# used where import_memories expects a bare connection). Fixed in Etapa 2.
# ---------------------------------------------------------------------------

def test_import_repo_scope_inserts(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    jsonl_path = tmp_path / "repo-import.jsonl"
    jsonl_path.write_text(
        json.dumps({
            "id": 501, "type": "fact", "scope": "repo",
            "statement": "repo-scoped import test", "confidence": "high",
            "created_at": "2026-07-14T00:00:00.000Z",
            "last_verified_at": "2026-07-14T00:00:00.000Z",
        }) + "\n"
    )

    result = _run_cli("import", str(jsonl_path), "--repo", str(repo))

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "Imported: 1" in result.stdout

    show = _run_cli("show", "501", "--repo", str(repo), "--json")
    assert show.returncode == 0, show.stderr
    assert json.loads(show.stdout)["statement"] == "repo-scoped import test"


# ---------------------------------------------------------------------------
# Etapa 1 case 2: import without created_at/last_verified_at should default,
# not crash with a raw sqlite3.IntegrityError. Fixed in Etapa 2.
# ---------------------------------------------------------------------------

def test_import_missing_created_at_uses_default(tmp_path, monkeypatch):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(tmp_path / "global.db"))

    jsonl_path = tmp_path / "no-ts.jsonl"
    jsonl_path.write_text(
        json.dumps({
            "id": 502, "type": "fact", "scope": "global",
            "statement": "no timestamp supplied", "confidence": "high",
            "assumptions": "local-first, single-user",
        }) + "\n"
    )

    result = _run_cli("import", str(jsonl_path), "--repo", str(repo))

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "IntegrityError" not in result.stderr
    assert "Imported: 1" in result.stdout


# ---------------------------------------------------------------------------
# Etapa 1 case 3: import must apply the same validation as `record` --
# scope=global without assumptions is rejected, not silently inserted.
# Fixed in Etapa 2.
# ---------------------------------------------------------------------------

def test_import_global_scope_without_assumptions_rejected(tmp_path, monkeypatch):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(tmp_path / "global.db"))

    jsonl_path = tmp_path / "bad-global.jsonl"
    jsonl_path.write_text(
        json.dumps({
            "id": 503, "type": "lesson", "scope": "global",
            "statement": "global lesson with no assumptions",
            "confidence": "high",
            "created_at": "2026-07-14T00:00:00.000Z",
            "last_verified_at": "2026-07-14T00:00:00.000Z",
        }) + "\n"
    )

    result = _run_cli("import", str(jsonl_path), "--repo", str(repo))

    assert result.returncode == 0, result.stderr
    assert "Imported: 0" in result.stdout
    assert "Skipped: 1" in result.stdout
    assert "assumptions" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Etapa 1 case 4: an invalid type/confidence must be a clean per-line skip,
# not a raw sqlite3 CHECK-constraint IntegrityError. Fixed in Etapa 2.
# ---------------------------------------------------------------------------

def test_import_invalid_type_skipped_with_warning(tmp_path, monkeypatch):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(tmp_path / "global.db"))

    jsonl_path = tmp_path / "bad-type.jsonl"
    jsonl_path.write_text(
        json.dumps({
            "id": 504, "type": "insight", "scope": "global",
            "statement": "invalid type value", "confidence": "high",
            "assumptions": "local-first, single-user",
            "created_at": "2026-07-14T00:00:00.000Z",
            "last_verified_at": "2026-07-14T00:00:00.000Z",
        }) + "\n"
    )

    result = _run_cli("import", str(jsonl_path), "--repo", str(repo))

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "IntegrityError" not in result.stderr
    assert "Imported: 0" in result.stdout
    assert "Skipped: 1" in result.stdout


# ---------------------------------------------------------------------------
# Etapa 1 case 5: import is idempotent -- already correct today for the
# global-scope, fully-specified-fields path (does not touch the repo-scope
# tuple bug), kept as a non-xfail baseline so a regression is caught.
# ---------------------------------------------------------------------------

def test_import_idempotent_global_scope(tmp_path, monkeypatch):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(tmp_path / "global.db"))

    jsonl_path = tmp_path / "idempotent.jsonl"
    jsonl_path.write_text(
        json.dumps({
            "id": 505, "type": "fact", "scope": "global",
            "statement": "idempotent import test", "confidence": "high",
            "assumptions": "local-first, single-user",
            "created_at": "2026-07-14T00:00:00.000Z",
            "last_verified_at": "2026-07-14T00:00:00.000Z",
        }) + "\n"
    )

    first = _run_cli("import", str(jsonl_path), "--repo", str(repo))
    assert first.returncode == 0, first.stderr
    assert "Imported: 1" in first.stdout

    second = _run_cli("import", str(jsonl_path), "--repo", str(repo))
    assert second.returncode == 0, second.stderr
    assert "Imported: 0" in second.stdout
    assert "Skipped: 1" in second.stdout


# ---------------------------------------------------------------------------
# Etapa 1 case 6: round-trip record -> export -> fresh repo -> import -> show,
# for scope=repo (the case that hit the tuple bug). Fixed in Etapa 2.
# ---------------------------------------------------------------------------

def test_round_trip_record_export_import_show_repo_scope(tmp_path):
    source_repo = build_fixture_repo_a(tmp_path / "source")
    _init(source_repo)
    memory_id = _record(
        source_repo, statement="round trip repo fact", type="fact",
        scope="repo", confidence="medium",
    )

    export_path = tmp_path / "repo-export.jsonl"
    export_result = _run_cli(
        "export", "--repo", str(source_repo), "--scope", "repo",
        "--output", str(export_path),
    )
    assert export_result.returncode == 0, export_result.stderr

    dest_repo = build_fixture_repo_a(tmp_path / "dest")
    _init(dest_repo)
    import_result = _run_cli("import", str(export_path), "--repo", str(dest_repo))
    assert import_result.returncode == 0, import_result.stderr
    assert "Imported: 1" in import_result.stdout

    show = _run_cli("show", str(memory_id), "--repo", str(dest_repo), "--json")
    assert show.returncode == 0, show.stderr
    payload = json.loads(show.stdout)
    assert payload["statement"] == "round trip repo fact"
    assert payload["confidence"] == "medium"


# ---------------------------------------------------------------------------
# Etapa 1 case 7: merge already gets confidence/tie resolution right
# structurally today (locked in as a baseline); only the human-readable
# message format needs to be aligned with EXPORT_IMPORT.md (Etapa 2).
# ---------------------------------------------------------------------------

def test_merge_confidence_conflict_high_wins(tmp_path):
    file1 = tmp_path / "kb1.jsonl"
    file2 = tmp_path / "kb2.jsonl"
    file1.write_text(json.dumps({
        "id": 1, "scope": "global", "confidence": "medium",
        "statement": "low-confidence version", "created_at": "2026-07-01T00:00:00Z",
    }) + "\n")
    file2.write_text(json.dumps({
        "id": 1, "scope": "global", "confidence": "high",
        "statement": "high-confidence version", "created_at": "2026-07-02T00:00:00Z",
    }) + "\n")

    memories, result = merge_jsonl(str(file1), str(file2))

    assert result.conflict_count == 1
    assert result.total == 1
    assert memories[(1, "global")]["statement"] == "high-confidence version"


def test_merge_tie_break_by_created_at(tmp_path):
    file1 = tmp_path / "kb1.jsonl"
    file2 = tmp_path / "kb2.jsonl"
    file1.write_text(json.dumps({
        "id": 1, "scope": "global", "confidence": "high",
        "statement": "older", "created_at": "2026-07-01T00:00:00Z",
    }) + "\n")
    file2.write_text(json.dumps({
        "id": 1, "scope": "global", "confidence": "high",
        "statement": "newer", "created_at": "2026-07-10T00:00:00Z",
    }) + "\n")

    memories, result = merge_jsonl(str(file1), str(file2))

    assert result.conflict_count == 1
    assert memories[(1, "global")]["statement"] == "newer"


def test_merge_conflict_message_matches_docs(tmp_path):
    file1 = tmp_path / "kb1.jsonl"
    file2 = tmp_path / "kb2.jsonl"
    file1.write_text(json.dumps({
        "id": 3, "scope": "global", "confidence": "medium",
        "statement": "medium version", "created_at": "2026-07-01T00:00:00Z",
    }) + "\n")
    file2.write_text(json.dumps({
        "id": 3, "scope": "global", "confidence": "high",
        "statement": "high version", "created_at": "2026-07-02T00:00:00Z",
    }) + "\n")
    output = tmp_path / "merged.jsonl"

    result = _run_cli("merge", str(file1), str(file2), "--output", str(output))

    assert result.returncode == 0, result.stderr
    # EXPORT_IMPORT.md's documented format: "picked high over medium"
    assert "picked high over medium" in result.stdout


def test_merge_missing_input_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        merge_jsonl(str(tmp_path / "nope1.jsonl"), str(tmp_path / "nope2.jsonl"))


def test_cli_merge_missing_file_exits_cleanly(tmp_path):
    output = tmp_path / "out.jsonl"
    result = _run_cli(
        "merge", str(tmp_path / "nope1.jsonl"), str(tmp_path / "nope2.jsonl"),
        "--output", str(output),
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# Etapa 1 case 8: retrieve/affected on a repo with zero commits must fail
# with a clean, explanatory message -- not a raw CalledProcessError.
# ---------------------------------------------------------------------------

def test_cli_retrieve_no_commits_clean_error(tmp_path):
    repo = tmp_path / "empty-repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "fixture@robo-cortex.test")
    run_git(repo, "config", "user.name", "robo-cortex fixture")
    _init(repo)

    result = _run_cli("retrieve", "--repo", str(repo), "--task", "anything")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "no commits" in result.stderr.lower() or "no commits" in result.stdout.lower()


def test_cli_affected_no_commits_clean_error(tmp_path):
    repo = tmp_path / "empty-repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "fixture@robo-cortex.test")
    run_git(repo, "config", "user.name", "robo-cortex fixture")
    _init(repo)

    result = _run_cli("affected", "--repo", str(repo))

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "no commits" in result.stderr.lower() or "no commits" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Etapa 1 case 9: export from an uninitialized repo already exits cleanly
# today -- non-xfail baseline.
# ---------------------------------------------------------------------------

def test_export_uninitialized_repo_clean_error(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    # deliberately skip _init(repo)

    result = _run_cli("export", "--repo", str(repo), "--scope", "repo")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# export_memories(): already correct, locked in as a baseline.
# ---------------------------------------------------------------------------

def test_export_memories_returns_rows_for_scope(tmp_path):
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO memory (type, scope, statement, confidence) VALUES (?, ?, ?, ?)",
        ("fact", "repo", "exported fact", "high"),
    )
    conn.commit()

    rows = export_memories(conn, "repo")

    assert len(rows) == 1
    assert rows[0]["statement"] == "exported fact"

    empty = export_memories(conn, "global")
    assert empty == []
