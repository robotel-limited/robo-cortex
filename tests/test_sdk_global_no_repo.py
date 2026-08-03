"""SDK counterpart to test_cli_global_no_repo.py: the same bug (every
method unconditionally called open_store() first, even for operations that
only ever touch the repo-independent ~/.cortex/global.db) existed in
RoboCortex too, not just the CLI -- see CHANGELOG 0.5.0.
"""

from robo_cortex.sdk import RoboCortex


def test_record_scope_global_works_with_no_repo_path_given(tmp_path, monkeypatch):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)

    cortex = RoboCortex()  # repo_path=None -> Path.cwd(), which isn't a repo
    result = cortex.record(
        type="lesson", statement="SDK global record with no repo.",
        scope="global", confidence="high", assumptions="single-user",
    )
    assert result["status"] == "provisional"


def test_get_memory_finds_a_global_memory_with_no_repo_context(tmp_path, monkeypatch):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)

    cortex = RoboCortex()
    recorded = cortex.record(
        type="lesson", statement="Findable via SDK from nowhere.",
        scope="global", confidence="high", assumptions="single-user",
    )

    fetched = cortex.get_memory(recorded["id"])
    assert fetched["statement"] == "Findable via SDK from nowhere."


def test_search_finds_a_global_memory_with_no_repo_context(tmp_path, monkeypatch):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)

    cortex = RoboCortex()
    cortex.record(
        type="lesson", statement="Searchable via SDK from nowhere.",
        scope="global", confidence="high", assumptions="single-user",
    )

    result = cortex.search("Searchable via SDK from nowhere")
    assert result["matched"] == 1
