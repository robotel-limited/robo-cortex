from pathlib import Path

import pytest

from robo_cortex.core.errors import AlreadyInitializedError, NotAGitRepoError
from robo_cortex.core.init import init_repo

from .fixtures import build_fixture_repo_a


def test_init_creates_cortex_dir_and_db(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    result = init_repo(str(repo))

    db_path = Path(result["db_path"])
    assert db_path.exists()
    assert db_path.parent.name == ".cortex"
    assert result["schema_version"] == 3
    assert Path(result["repo_root"]).resolve() == repo.resolve()


def test_init_writes_gitignore_entry(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    result = init_repo(str(repo))

    assert result["gitignore_updated"] is True
    lines = (repo / ".gitignore").read_text().splitlines()
    assert ".cortex/" in lines


def test_init_does_not_duplicate_existing_gitignore_entry(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    (repo / ".gitignore").write_text("node_modules/\n.cortex/\n")

    result = init_repo(str(repo))

    assert result["gitignore_updated"] is False
    content = (repo / ".gitignore").read_text()
    assert content.count(".cortex/") == 1


def test_init_appends_to_gitignore_missing_trailing_newline(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    (repo / ".gitignore").write_text("node_modules/")  # no trailing newline

    init_repo(str(repo))

    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines == ["node_modules/", ".cortex/"]


def test_init_refuses_non_git_directory_with_helpful_message(tmp_path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    with pytest.raises(NotAGitRepoError) as excinfo:
        init_repo(str(not_a_repo))

    assert "not inside a git repository" in str(excinfo.value)
    assert excinfo.value.exit_code == 1


def test_init_refuses_double_init(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    init_repo(str(repo))

    with pytest.raises(AlreadyInitializedError) as excinfo:
        init_repo(str(repo))

    assert excinfo.value.exit_code == 2


def test_init_works_from_a_subdirectory(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    subdir = repo / "src"

    result = init_repo(str(subdir))

    assert Path(result["repo_root"]).resolve() == repo.resolve()
