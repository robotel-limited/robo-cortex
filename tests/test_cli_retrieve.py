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


def _init_and_record(repo):
    assert _run_cli("init", "--repo", str(repo)).returncode == 0
    assert _run_cli(
        "record", "--repo", str(repo),
        "--type", "decision", "--scope", "repo",
        "--statement", "Scanner batches at 50 items because larger batches time out.",
        "--confidence", "high",
        "--path", "src/fixture_a/scanner.py",
    ).returncode == 0


def test_cli_retrieve_json_round_trip(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init_and_record(repo)

    result = _run_cli(
        "retrieve", "--repo", str(repo), "--task", "why does the scanner batch", "--json"
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["meta"]["matched"] == 1
    assert payload["data"][0]["statement"].startswith("Scanner batches")


def test_cli_retrieve_explain_shows_score_breakdown(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init_and_record(repo)

    result = _run_cli(
        "retrieve", "--repo", str(repo), "--task", "scanner batches", "--explain"
    )
    assert result.returncode == 0
    assert "text_match=" in result.stdout
    assert "total=" in result.stdout


def test_cli_retrieve_missing_task_exits_2(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init_and_record(repo)

    result = _run_cli("retrieve", "--repo", str(repo))
    assert result.returncode == 2
    assert "--task is required" in result.stderr
