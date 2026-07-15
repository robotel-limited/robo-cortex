"""roco hooks: the pre-commit enforcement layer robo-cortex actually ships.

Per raport-oportunitate.md's audit, the pre-0.3.0 README promised three
enforcement layers (git hooks, a decorator, a CI/CD gate) and shipped none
of them. This is the first one built for real -- these tests exercise the
whole path end to end: install the hook, stage a change touching a
memory's linked path, and confirm a real `git commit` is actually blocked
(and unblocked once the memory is reviewed, and bypassable with
--no-verify).
"""

import json
import subprocess
import sys

from robo_cortex.core.hooks import POST_COMMIT_HOOK_FILENAME, hook_path

from .fixtures import build_fixture_repo_a, run_git


def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _init(repo):
    result = _run_cli("init", "--repo", str(repo))
    assert result.returncode == 0, result.stderr


def _record_on_scanner(repo, statement="scanner is batch-sized deliberately"):
    result = _run_cli(
        "record", "--repo", str(repo), "--type", "decision", "--scope", "repo",
        "--statement", statement, "--confidence", "high",
        "--path", "src/fixture_a/scanner.py", "--json",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["id"]


def test_hooks_install_on_clean_repo(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = _run_cli("hooks", "install", "--repo", str(repo), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["installed"] is True
    assert payload["chained"] is False
    assert hook_path(repo).exists()
    assert hook_path(repo).stat().st_mode & 0o111  # executable


def test_hooks_status_reflects_install_state(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    before = _run_cli("hooks", "status", "--repo", str(repo), "--json")
    assert json.loads(before.stdout)["installed"] is False

    _run_cli("hooks", "install", "--repo", str(repo))

    after = _run_cli("hooks", "status", "--repo", str(repo), "--json")
    assert json.loads(after.stdout)["installed"] is True


def test_hooks_install_refuses_existing_hook_without_force(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    path = hook_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho 'not robo-cortex'\n")

    result = _run_cli("hooks", "install", "--repo", str(repo))

    assert result.returncode == 1
    assert "--force" in result.stderr
    assert "not robo-cortex" in path.read_text()


def test_hooks_install_force_chains_existing_hook(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    path = hook_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho 'existing hook ran'\n")

    result = _run_cli("hooks", "install", "--repo", str(repo), "--force", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["chained"] is True
    content = path.read_text()
    assert "existing hook ran" in content
    assert "robo-cortex pre-commit hook" in content


def test_hooks_uninstall_removes_hook_file_when_only_ours(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _run_cli("hooks", "install", "--repo", str(repo))
    assert hook_path(repo).exists()

    result = _run_cli("hooks", "uninstall", "--repo", str(repo), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["uninstalled"] is True
    assert payload["deleted"] is True
    assert not hook_path(repo).exists()


def test_hooks_uninstall_preserves_chained_hook_content(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    path = hook_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho 'existing hook ran'\n")
    _run_cli("hooks", "install", "--repo", str(repo), "--force")

    result = _run_cli("hooks", "uninstall", "--repo", str(repo), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["deleted"] is False
    remaining = path.read_text()
    assert "existing hook ran" in remaining
    assert "robo-cortex pre-commit hook" not in remaining


def test_hooks_check_passes_when_nothing_affected(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record_on_scanner(repo)

    (repo / "docs" / "adr-0001-storage.md").write_text("unrelated edit\n")
    run_git(repo, "add", "-A")

    result = _run_cli("hooks", "check", "--repo", str(repo))

    assert result.returncode == 0, result.stderr


def test_hooks_check_fails_when_memory_affected(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record_on_scanner(repo)

    scanner = repo / "src" / "fixture_a" / "scanner.py"
    scanner.write_text(scanner.read_text().replace("batch_size=50", "batch_size=200"))
    run_git(repo, "add", "-A")

    result = _run_cli("hooks", "check", "--repo", str(repo))

    assert result.returncode == 1
    assert f"[{memory_id}]" in result.stderr
    assert "git commit --no-verify" in result.stderr


def test_installed_hook_blocks_real_commit_touching_affected_memory(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record_on_scanner(repo)
    install_result = _run_cli("hooks", "install", "--repo", str(repo))
    assert install_result.returncode == 0, install_result.stderr

    scanner = repo / "src" / "fixture_a" / "scanner.py"
    scanner.write_text(scanner.read_text().replace("batch_size=50", "batch_size=200"))
    run_git(repo, "add", "-A")

    commit = subprocess.run(
        ["git", "commit", "-m", "Raise batch_size"],
        cwd=repo, capture_output=True, text=True,
    )

    assert commit.returncode != 0
    assert "memories that need review" in commit.stderr.lower()


def test_installed_hook_allows_commit_with_no_verify_bypass(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record_on_scanner(repo)
    _run_cli("hooks", "install", "--repo", str(repo))

    scanner = repo / "src" / "fixture_a" / "scanner.py"
    scanner.write_text(scanner.read_text().replace("batch_size=50", "batch_size=200"))
    run_git(repo, "add", "-A")

    commit = subprocess.run(
        ["git", "commit", "--no-verify", "-m", "Raise batch_size, bypassing the hook"],
        cwd=repo, capture_output=True, text=True,
    )

    assert commit.returncode == 0, commit.stderr


def test_installed_hook_allows_unrelated_commit(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record_on_scanner(repo)
    _run_cli("hooks", "install", "--repo", str(repo))

    (repo / "docs" / "adr-0001-storage.md").write_text("an unrelated doc edit\n")
    run_git(repo, "add", "-A")

    commit = subprocess.run(
        ["git", "commit", "-m", "Unrelated doc edit"],
        cwd=repo, capture_output=True, text=True,
    )

    assert commit.returncode == 0, commit.stderr


def test_installed_hook_with_missing_binary_fails_open(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record_on_scanner(repo)
    install_result = _run_cli("hooks", "install", "--repo", str(repo))
    assert install_result.returncode == 0

    hook_file = hook_path(repo)
    hook_content = hook_file.read_text()
    hook_content = hook_content.replace(
        'ROCO_CMD="',
        'ROCO_CMD="/nonexistent/roco'
    )
    hook_file.write_text(hook_content)

    scanner = repo / "src" / "fixture_a" / "scanner.py"
    scanner.write_text(scanner.read_text().replace("batch_size=50", "batch_size=200"))
    run_git(repo, "add", "-A")

    commit = subprocess.run(
        ["git", "commit", "-m", "Edit despite missing binary"],
        cwd=repo, capture_output=True, text=True,
    )

    assert commit.returncode == 0, "Hook should fail-open when binary is missing"
    assert "binary not found" in commit.stderr.lower()


def test_post_commit_hooks_install_on_clean_repo(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = _run_cli("hooks", "install", "--post-commit", "--repo", str(repo), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["installed"] is True
    assert payload["chained"] is False
    post_commit_path = hook_path(repo, POST_COMMIT_HOOK_FILENAME)
    assert post_commit_path.exists()
    assert post_commit_path.stat().st_mode & 0o111  # executable


def test_pre_commit_and_post_commit_hooks_coexist(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    _run_cli("hooks", "install", "--repo", str(repo))
    _run_cli("hooks", "install", "--post-commit", "--repo", str(repo))

    assert hook_path(repo).exists()
    assert hook_path(repo, POST_COMMIT_HOOK_FILENAME).exists()
    assert "robo-cortex pre-commit hook" in hook_path(repo).read_text()
    assert "robo-cortex post-commit hook" in hook_path(repo, POST_COMMIT_HOOK_FILENAME).read_text()


def test_post_commit_hooks_status_reflects_install_state(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    before = _run_cli("hooks", "status", "--post-commit", "--repo", str(repo), "--json")
    assert json.loads(before.stdout)["installed"] is False

    _run_cli("hooks", "install", "--post-commit", "--repo", str(repo))

    after = _run_cli("hooks", "status", "--post-commit", "--repo", str(repo), "--json")
    assert json.loads(after.stdout)["installed"] is True

    # --status without --post-commit still reports only pre-commit, unaffected
    pre_commit_only = _run_cli("hooks", "status", "--repo", str(repo), "--json")
    assert json.loads(pre_commit_only.stdout)["installed"] is False


def test_post_commit_hooks_uninstall_does_not_affect_pre_commit(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _run_cli("hooks", "install", "--repo", str(repo))
    _run_cli("hooks", "install", "--post-commit", "--repo", str(repo))

    result = _run_cli("hooks", "uninstall", "--post-commit", "--repo", str(repo), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["uninstalled"] is True
    assert payload["deleted"] is True
    assert not hook_path(repo, POST_COMMIT_HOOK_FILENAME).exists()
    assert hook_path(repo).exists()  # pre-commit untouched


def test_installed_post_commit_hook_reports_without_blocking(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record_on_scanner(repo)
    install_result = _run_cli("hooks", "install", "--post-commit", "--repo", str(repo))
    assert install_result.returncode == 0, install_result.stderr

    scanner = repo / "src" / "fixture_a" / "scanner.py"
    scanner.write_text(scanner.read_text().replace("batch_size=50", "batch_size=200"))
    run_git(repo, "add", "-A")

    commit = subprocess.run(
        ["git", "commit", "-m", "Raise batch_size"],
        cwd=repo, capture_output=True, text=True,
    )

    assert commit.returncode == 0, commit.stderr
    # git forwards a hook's own stdout to git's stderr stream (distinct from
    # git commit's own porcelain output on stdout, e.g. "[master abc123] ...").
    assert f"[{memory_id}]" in commit.stderr


def test_installed_post_commit_hook_skips_first_commit_in_repo(tmp_path):
    """HEAD~1 doesn't exist for a repo's very first commit -- the hook must
    skip the diff (and exit 0) instead of letting `git rev-parse` fail."""
    repo = tmp_path / "brand-new-repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "t@t")
    run_git(repo, "config", "user.name", "t")
    _init(repo)
    _run_cli("hooks", "install", "--post-commit", "--repo", str(repo))

    (repo / "README.md").write_text("# brand new repo\n")
    run_git(repo, "add", "-A")

    commit = subprocess.run(
        ["git", "commit", "-m", "first commit"],
        cwd=repo, capture_output=True, text=True,
    )

    assert commit.returncode == 0, commit.stderr


