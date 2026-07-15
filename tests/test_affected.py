from robo_cortex.core.db import connect, migrate
from robo_cortex.core.invalidate import affected
from robo_cortex.core.memory import record_memory

from .fixtures import build_fixture_repo_a, run_git


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_affected_reports_uncommitted_working_tree_edit(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")

    report = affected(conn, repo)

    assert report["matched"] == 1
    assert report["data"][0]["id"] == result["id"]
    assert report["data"][0]["reason"] == "path_changed:src/fixture_a/scanner.py@working_tree"


def test_affected_does_not_mutate_status(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")

    affected(conn, repo)

    status = conn.execute("SELECT status FROM memory WHERE id = ?", (result["id"],)).fetchone()[0]
    assert status == "provisional"  # unchanged: affected reports, it does not flag


def test_affected_reports_staged_change(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    (repo / "src" / "fixture_a" / "exporter.py").write_text("def export_csv(rows): return ','.join(rows)\n")
    run_git(repo, "add", "-A")

    report = affected(conn, repo, staged=True)

    assert report["data"][0]["id"] == result["id"]


def test_affected_with_explicit_diff_range(tmp_path):
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    before_sha = run_git_output(repo, "rev-parse", "HEAD")

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "change scanner")
    after_sha = run_git_output(repo, "rev-parse", "HEAD")

    report = affected(conn, repo, diff_range=f"{before_sha}..{after_sha}")

    assert report["data"][0]["id"] == result["id"]
    assert report["data"][0]["reason"] == f"path_changed:src/fixture_a/scanner.py@{before_sha}..{after_sha}"


def test_affected_untouched_paths_never_reported(tmp_path):
    repo, conn = _store(tmp_path)
    record_memory(
        conn, repo, type="fact", scope="repo", confidence="low",
        statement="The exporter joins rows with a semicolon.",
        paths=["src/fixture_a/exporter.py"],
    )
    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")

    report = affected(conn, repo)

    assert report["matched"] == 0


def run_git_output(repo, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_affected_excludes_terminal_status_memories(tmp_path):
    """A superseded memory linked to a touched path must not be reported
    'at risk' -- it isn't at risk, it's already history."""
    repo, conn = _store(tmp_path)
    result = record_memory(
        conn, repo, type="decision", scope="repo", confidence="high",
        statement="Scanner batches at 50 items.",
        paths=["src/fixture_a/scanner.py"],
    )
    conn.execute("UPDATE memory SET status = 'superseded' WHERE id = ?", (result["id"],))

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")

    report = affected(conn, repo)

    assert report["matched"] == 0
    assert report["data"] == []
