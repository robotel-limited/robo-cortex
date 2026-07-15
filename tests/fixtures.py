"""Builders for the two fixture Git repositories used by the test suite.

Repo A is the primary fixture exercised by most stages. Repo B exists solely
to exercise cross-project scope-B retrieval (Stage 8). Both are built fresh
per call (typically against a pytest `tmp_path`) so tests stay hermetic even
when they go on to edit and commit into the fixture themselves (Stage 6's
git-scenario tests).
"""

import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str) -> None:
    """Public helper for git-scenario tests (Stage 6+) to edit/commit/mv/revert
    inside a fixture repo after it's built."""
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


_git = run_git


def add_remote(repo: Path, url: str, remote_name: str = "origin") -> None:
    """Set a git remote on an already-built fixture repo (Stage 10: Gitea
    owner/repo resolution reads this via `git remote get-url`)."""
    _git(repo, "remote", "add", remote_name, url)


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@robo-cortex.test")
    _git(repo, "config", "user.name", "robo-cortex fixture")


def build_fixture_repo_a(tmp_path: Path) -> Path:
    """Primary fixture: a small multi-subsystem project with real history."""
    repo = tmp_path / "fixture-repo-a"
    _init_git_repo(repo)

    (repo / "README.md").write_text(
        "# fixture-repo-a\n\n"
        "A small fixture project used by robo-cortex's own test suite.\n"
    )
    (repo / "CLAUDE.md").write_text(
        "# Project notes\n\n"
        "- The scanner processes items in batches of 50 because larger "
        "batches time out on the shared staging host.\n"
        "- CSV exports use a semicolon delimiter for compatibility with the "
        "downstream billing system.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Initial commit: README and project notes")

    src = repo / "src" / "fixture_a"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "scanner.py").write_text(
        "def scan_batch(items, batch_size=50):\n"
        '    """Scan items in fixed-size batches."""\n'
        "    for i in range(0, len(items), batch_size):\n"
        "        yield items[i : i + batch_size]\n"
    )
    (src / "exporter.py").write_text(
        'def export_csv(rows, delimiter=";"):\n'
        "    return delimiter.join(rows)\n"
    )
    api = src / "api"
    api.mkdir()
    (api / "__init__.py").write_text("")
    (api / "routes.py").write_text(
        "def health_check():\n"
        '    return "ok"\n'
    )

    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_scanner.py").write_text(
        "from fixture_a.scanner import scan_batch\n\n\n"
        "def test_scan_batch():\n"
        "    assert list(scan_batch([1, 2, 3], batch_size=2)) == [[1, 2], [3]]\n"
    )

    docs = repo / "docs"
    docs.mkdir()
    (docs / "adr-0001-storage.md").write_text(
        "# ADR 0001: use SQLite for local storage\n\n"
        "We use SQLite instead of Postgres because this is a local-first, "
        "single-user tool with no server to run.\n"
    )

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Add scanner, exporter, api, tests, and an ADR")

    return repo


def build_fixture_repo_b(tmp_path: Path) -> Path:
    """Secondary fixture: unrelated content, used only to exercise scope-B retrieval."""
    repo = tmp_path / "fixture-repo-b"
    _init_git_repo(repo)

    (repo / "README.md").write_text(
        "# fixture-repo-b\n\n"
        "A second, unrelated fixture project used only to test that reusable "
        "(scope B) memory crosses repositories correctly.\n"
    )

    src = repo / "src" / "fixture_b"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "worker.py").write_text(
        "def process_queue(queue):\n"
        "    while queue:\n"
        "        yield queue.pop(0)\n"
    )

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Initial commit: worker module")

    return repo
