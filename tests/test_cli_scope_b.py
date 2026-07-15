import json
import subprocess
import sys

from .fixtures import build_fixture_repo_a, build_fixture_repo_b


def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_cli_cross_repo_lesson_fires_only_on_assumption_match(tmp_path):
    repo_a = build_fixture_repo_a(tmp_path / "a")
    repo_b = build_fixture_repo_b(tmp_path / "b")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    assert _run_cli("init", "--repo", str(repo_b)).returncode == 0

    record = _run_cli(
        "record", "--repo", str(repo_a),
        "--type", "lesson", "--scope", "global", "--confidence", "high",
        "--statement", "Prefer SQLite over Postgres for this kind of tool.",
        "--assumptions", "single-user, local-first",
        "--json",
    )
    assert record.returncode == 0

    matching = _run_cli(
        "retrieve", "--repo", str(repo_b),
        "--task", "choosing a database for a single-user local-first tool",
        "--json",
    )
    assert matching.returncode == 0
    matching_payload = json.loads(matching.stdout)
    assert matching_payload["meta"]["matched"] == 1
    assert matching_payload["data"][0]["scope"] == "global"

    non_matching = _run_cli(
        "retrieve", "--repo", str(repo_b),
        "--task", "choosing a database for a distributed multi-tenant service",
        "--json",
    )
    assert non_matching.returncode == 0
    non_matching_payload = json.loads(non_matching.stdout)
    assert non_matching_payload["meta"]["matched"] == 0


def test_cli_repo_memories_never_leak_between_fixtures(tmp_path):
    repo_a = build_fixture_repo_a(tmp_path / "a")
    repo_b = build_fixture_repo_b(tmp_path / "b")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    assert _run_cli("init", "--repo", str(repo_b)).returncode == 0

    assert _run_cli(
        "record", "--repo", str(repo_a),
        "--type", "decision", "--scope", "repo", "--confidence", "high",
        "--statement", "Scanner batches at fifty items in fixture A.",
    ).returncode == 0

    result = _run_cli("list", "--repo", str(repo_b), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_cli_show_finds_global_memory_from_a_different_repo(tmp_path):
    repo_a = build_fixture_repo_a(tmp_path / "a")
    repo_b = build_fixture_repo_b(tmp_path / "b")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    assert _run_cli("init", "--repo", str(repo_b)).returncode == 0

    record = _run_cli(
        "record", "--repo", str(repo_a),
        "--type", "lesson", "--scope", "global", "--confidence", "high",
        "--statement", "A globally reusable lesson.",
        "--assumptions", "single-user",
        "--json",
    )
    assert record.returncode == 0, record.stderr
    memory_id = json.loads(record.stdout)["id"]

    # show from fixture B's context -- the memory lives in the global
    # store, not repo A's or repo B's local store
    result = _run_cli("show", str(memory_id), "--repo", str(repo_b), "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["statement"] == "A globally reusable lesson."
    assert payload["scope"] == "global"


def test_cli_explain_human_readable_output_on_global_item_does_not_crash(tmp_path):
    """Regression: --explain's human-readable formatter blindly ran every
    score component through `:.3f`, including assumptions_gate -- a nested
    dict, present only on scope='global' items. JSON-output CLI tests never
    exercise this code path at all (json.dumps doesn't care about types),
    so only a plain-text invocation catches it -- caught by the fresh-venv
    manual run, not by any of this suite's --json-only CLI tests, all of
    which stayed green throughout."""
    repo_a = build_fixture_repo_a(tmp_path / "a")
    repo_b = build_fixture_repo_b(tmp_path / "b")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0
    assert _run_cli("init", "--repo", str(repo_b)).returncode == 0

    assert _run_cli(
        "record", "--repo", str(repo_a),
        "--type", "lesson", "--scope", "global", "--confidence", "high",
        "--statement", "Prefer SQLite over Postgres for local-first single-user tools.",
        "--assumptions", "single-user, local-first",
    ).returncode == 0

    retrieve_result = _run_cli(
        "retrieve", "--repo", str(repo_b),
        "--task", "database choice for a single-user local-first tool",
        "--explain",
    )
    assert retrieve_result.returncode == 0
    assert "assumptions_gate=" in retrieve_result.stdout
    assert "passed=True" in retrieve_result.stdout

    memory_id = 1
    show_result = _run_cli(
        "show", str(memory_id), "--repo", str(repo_b),
        "--explain-against", "database choice for a single-user local-first tool",
    )
    assert show_result.returncode == 0
    assert "assumptions_gate=" in show_result.stdout


def test_cli_scope_disambiguates_a_colliding_id(tmp_path):
    """Proven live: a local id 1 shadows global id 1 for show/status/
    evidence without a way to say which store is meant. --scope fixes it."""
    repo_a = build_fixture_repo_a(tmp_path / "a")
    assert _run_cli("init", "--repo", str(repo_a)).returncode == 0

    local_record = _run_cli(
        "record", "--repo", str(repo_a),
        "--type", "fact", "--scope", "repo", "--confidence", "low",
        "--statement", "a local fact", "--json",
    )
    global_record = _run_cli(
        "record", "--repo", str(repo_a),
        "--type", "lesson", "--scope", "global", "--confidence", "high",
        "--statement", "a global lesson", "--assumptions", "single-user",
        "--json",
    )
    local_id = json.loads(local_record.stdout)["id"]
    global_id = json.loads(global_record.stdout)["id"]
    assert local_id == global_id  # the collision this test is about

    # without disambiguation, the local one shadows the global one
    default_show = _run_cli("show", str(local_id), "--repo", str(repo_a), "--json")
    assert json.loads(default_show.stdout)["statement"] == "a local fact"

    # --scope reaches each one unambiguously
    repo_show = _run_cli("show", str(local_id), "--repo", str(repo_a), "--scope", "repo", "--json")
    global_show = _run_cli("show", str(global_id), "--repo", str(repo_a), "--scope", "global", "--json")
    assert json.loads(repo_show.stdout)["statement"] == "a local fact"
    assert json.loads(global_show.stdout)["statement"] == "a global lesson"
