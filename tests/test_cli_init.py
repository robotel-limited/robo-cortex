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


def test_cli_init_success(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    result = _run_cli("init", "--repo", str(repo))

    assert result.returncode == 0
    assert (repo / ".cortex" / "memory.db").exists()
    assert "Initialized robo-cortex" in result.stdout


def test_cli_init_json_output(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    result = _run_cli("init", "--repo", str(repo), "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 3
    assert payload["gitignore_updated"] is True


def test_cli_init_refuses_non_git_directory(tmp_path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    result = _run_cli("init", "--repo", str(not_a_repo))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "not inside a git repository" in result.stderr


def test_cli_init_already_initialized_exits_2(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _run_cli("init", "--repo", str(repo))

    result = _run_cli("init", "--repo", str(repo))

    assert result.returncode == 2
    assert "already initialized" in result.stderr


def test_cli_init_global_creates_store(tmp_path, monkeypatch):
    global_db = tmp_path / "global.db"
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(global_db))

    result = _run_cli("init", "--global")

    assert result.returncode == 0
    assert global_db.exists()
    assert "Initialized robo-cortex global store" in result.stdout
    assert str(global_db) in result.stdout


def test_cli_init_global_does_not_require_git_repo(tmp_path, monkeypatch):
    global_db = tmp_path / "global.db"
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(global_db))
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    result = _run_cli("init", "--global", cwd=str(not_a_repo))

    assert result.returncode == 0
    assert global_db.exists()


def test_cli_init_global_json_output(tmp_path, monkeypatch):
    global_db = tmp_path / "global.db"
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(global_db))

    result = _run_cli("init", "--global", "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["db_path"] == str(global_db)


def test_cli_init_global_is_idempotent(tmp_path, monkeypatch):
    global_db = tmp_path / "global.db"
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(global_db))

    first = _run_cli("init", "--global")
    second = _run_cli("init", "--global")

    assert first.returncode == 0
    assert second.returncode == 0
    assert global_db.exists()


def test_cli_init_global_disabled_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBO_CORTEX_NO_GLOBAL", "1")

    result = _run_cli("init", "--global")

    assert result.returncode == 1
    assert "disabled" in result.stderr
