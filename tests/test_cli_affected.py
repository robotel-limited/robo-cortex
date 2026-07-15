import json
import subprocess
import sys

from .fixtures import build_fixture_repo_a


def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_cli_affected_reports_working_tree_edit(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    assert _run_cli("init", "--repo", str(repo)).returncode == 0
    record = _run_cli(
        "record", "--repo", str(repo),
        "--type", "decision", "--scope", "repo",
        "--statement", "Scanner batches at 50 items.",
        "--confidence", "high",
        "--path", "src/fixture_a/scanner.py",
        "--json",
    )
    memory_id = json.loads(record.stdout)["id"]

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")

    result = _run_cli("affected", "--repo", str(repo), "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["data"][0]["id"] == memory_id
    assert "working_tree" in payload["data"][0]["reason"]


def test_cli_affected_no_changes_reports_nothing(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    assert _run_cli("init", "--repo", str(repo)).returncode == 0

    result = _run_cli("affected", "--repo", str(repo))
    assert result.returncode == 0
    assert "No memories affected." in result.stdout


def test_cli_show_prints_status_reason_after_committed_change(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    assert _run_cli("init", "--repo", str(repo)).returncode == 0
    record = _run_cli(
        "record", "--repo", str(repo),
        "--type", "decision", "--scope", "repo",
        "--statement", "Scanner batches at 50 items.",
        "--confidence", "high",
        "--path", "src/fixture_a/scanner.py",
        "--json",
    )
    memory_id = json.loads(record.stdout)["id"]

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "edit"], cwd=repo, check=True, capture_output=True
    )
    _run_cli("affected", "--repo", str(repo))  # trigger the lazy staleness check

    result = _run_cli("show", str(memory_id), "--repo", str(repo))
    assert result.returncode == 0
    assert "needs_review" in result.stdout
    assert "status reason: path_changed:src/fixture_a/scanner.py" in result.stdout
