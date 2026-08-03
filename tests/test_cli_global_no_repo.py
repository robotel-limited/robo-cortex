"""Global-scope (scope='global') operations must not require a *local*
repo store to be resolvable -- ~/.cortex/global.db (ROBO_CORTEX_GLOBAL_DB in
tests) is independent of any repo by construction (ARCHITECTURE.md §2), but
every ID-taking/searching command used to unconditionally call open_store()
first and hard-fail if the caller wasn't inside an already-initialized git
repo, even when the actual operation never touched the local store at all.
Reported live (prompt-bug-roco.md-style friction): recording and then
re-finding a global lesson required trial-and-erroring across several
directories to land on one that happened to be a valid, initialized repo,
for no reason the global store itself needed.
"""

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


def _record_global(cwd, statement="A globally reusable lesson, recorded with no repo."):
    return _run_cli(
        "record",
        "--type", "lesson", "--scope", "global", "--confidence", "high",
        "--statement", statement,
        "--assumptions", "single-user",
        "--json",
        cwd=cwd,
    )


def test_record_scope_global_works_outside_any_git_repo(tmp_path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    result = _record_global(str(not_a_repo))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "provisional"


def test_record_scope_global_works_in_a_never_initialized_git_repo(tmp_path):
    uninitialized_repo = tmp_path / "git-repo-no-roco-init"
    uninitialized_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=uninitialized_repo, check=True)

    result = _record_global(str(uninitialized_repo))

    assert result.returncode == 0, result.stderr
    assert not (uninitialized_repo / ".cortex").exists()  # never touched the local store


def test_show_finds_a_global_memory_with_no_repo_context_at_all(tmp_path):
    repo_a = build_fixture_repo_a(tmp_path / "a")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    record = _record_global(str(repo_a), statement="Findable from nowhere.")
    memory_id = json.loads(record.stdout)["id"]

    not_a_repo = tmp_path / "nowhere"
    not_a_repo.mkdir()
    result = _run_cli("show", str(memory_id), "--json", cwd=str(not_a_repo))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["statement"] == "Findable from nowhere."


def test_search_finds_a_global_memory_with_no_repo_context_at_all(tmp_path):
    repo_a = build_fixture_repo_a(tmp_path / "a")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    assert _record_global(str(repo_a), statement="Searchable from nowhere.").returncode == 0

    not_a_repo = tmp_path / "nowhere"
    not_a_repo.mkdir()
    result = _run_cli(
        "search", "--query", "Searchable from nowhere", "--json", cwd=str(not_a_repo)
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["matched"] == 1
    assert payload["data"][0]["statement"] == "Searchable from nowhere."


def test_retrieve_deliberately_still_requires_a_real_repo(tmp_path):
    """Unlike show/search/status/.../record --scope global above, `retrieve`
    is NOT relaxed: its whole purpose is local-repo-aware context, so an
    uninitialized/nonexistent repo should fail loudly rather than silently
    return degraded, global-only results that could read as "nothing
    relevant here" when the real problem is the missing local store. Same
    boundary the SDK pins in test_sdk.py::
    test_retrieve_on_uninitialized_repo_raises_not_initialized."""
    not_a_repo = tmp_path / "nowhere"
    not_a_repo.mkdir()
    result = _run_cli(
        "retrieve", "--task", "anything", cwd=str(not_a_repo),
    )

    assert result.returncode != 0
    assert "not inside a git repository" in result.stderr


def test_show_explicit_scope_repo_gives_a_clear_error_with_no_repo(tmp_path):
    repo_a = build_fixture_repo_a(tmp_path / "a")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    record = _record_global(str(repo_a))
    memory_id = json.loads(record.stdout)["id"]

    not_a_repo = tmp_path / "nowhere"
    not_a_repo.mkdir()
    result = _run_cli(
        "show", str(memory_id), "--scope", "repo", "--json", cwd=str(not_a_repo)
    )

    assert result.returncode != 0
    assert "no repo store available" in result.stderr
    assert "--scope repo" in result.stderr


def test_list_scope_repo_gives_a_clear_error_with_no_repo(tmp_path):
    not_a_repo = tmp_path / "nowhere"
    not_a_repo.mkdir()
    result = _run_cli("list", "--scope", "repo", cwd=str(not_a_repo))

    assert result.returncode == 2
    assert "no repo store available" in result.stderr


def test_repo_scoped_record_still_requires_a_real_repo(tmp_path):
    """The fix is scoped to global-only operations -- a repo-scoped record
    must still fail loudly outside a git repo, exactly as before."""
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    result = _run_cli(
        "record",
        "--type", "fact", "--scope", "repo", "--confidence", "low",
        "--statement", "This should never be written anywhere.",
        cwd=str(not_a_repo),
    )

    assert result.returncode != 0
    assert not (not_a_repo / ".cortex").exists()
