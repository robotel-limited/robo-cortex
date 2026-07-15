import json
import subprocess
import sys

from .fixtures import build_fixture_repo_a


def _run_cli(*args, cwd=None, input=None):
    return subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
    )


def _init(repo):
    result = _run_cli("init", "--repo", str(repo))
    assert result.returncode == 0


def test_cli_record_then_show_round_trip(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    record_result = _run_cli(
        "record", "--repo", str(repo),
        "--type", "decision", "--scope", "repo",
        "--statement", "Scanner batches at 50 items.",
        "--confidence", "high",
        "--path", "src/fixture_a/scanner.py",
        "--json",
    )
    assert record_result.returncode == 0
    payload = json.loads(record_result.stdout)
    memory_id = payload["id"]

    show_result = _run_cli("show", str(memory_id), "--repo", str(repo), "--json")
    assert show_result.returncode == 0
    shown = json.loads(show_result.stdout)
    assert shown["statement"] == "Scanner batches at 50 items."
    assert shown["paths"][0]["path"] == "src/fixture_a/scanner.py"


def test_cli_record_missing_required_fields_exits_2(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = _run_cli("record", "--repo", str(repo), "--type", "fact")
    assert result.returncode == 2
    assert "are required" in result.stderr


def test_cli_record_dead_path_exits_1(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = _run_cli(
        "record", "--repo", str(repo),
        "--type", "fact", "--scope", "repo",
        "--statement", "links nowhere",
        "--confidence", "low",
        "--path", "no/such/file.py",
    )
    assert result.returncode == 1
    assert "does not exist at HEAD" in result.stderr
    assert "Commit the file first" in result.stderr


def test_cli_record_batch_via_stdin(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    payload = "\n".join([
        json.dumps({"type": "fact", "scope": "repo", "statement": "one", "confidence": "low"}),
        json.dumps({"type": "fact", "scope": "repo", "statement": "x" * 501, "confidence": "low"}),
        json.dumps({"type": "fact", "scope": "repo", "statement": "two", "confidence": "high"}),
    ])

    result = _run_cli("record", "--repo", str(repo), "--batch", "--json", input=payload)
    assert result.returncode == 0
    summary = json.loads(result.stdout)
    assert summary["created"] == 2
    assert len(summary["failed"]) == 1


def test_cli_list_shows_recorded_memories(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _run_cli(
        "record", "--repo", str(repo), "--type", "fact", "--scope", "repo",
        "--statement", "listed memory", "--confidence", "low",
    )

    result = _run_cli("list", "--repo", str(repo), "--json")
    assert result.returncode == 0
    items = json.loads(result.stdout)
    assert any(item["statement"] == "listed memory" for item in items)


def test_cli_show_unknown_id_exits_1(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = _run_cli("show", "999", "--repo", str(repo))
    assert result.returncode == 1
    assert "no memory with id 999" in result.stderr


def test_cli_record_help_only_mentions_real_types():
    """Regression guard: --help's example types must be ones --type
    actually accepts (TYPES in core/memory.py). raport-oportunitate.md's
    audit caught 'decision, bug, insight, etc.' in the help text, where
    'bug' and 'insight' were never valid --type values."""
    from robo_cortex.core.memory import TYPES

    result = _run_cli("record", "--help")
    assert result.returncode == 0

    help_text = result.stdout.lower()
    type_line_start = help_text.index("memory type:")
    type_line = help_text[type_line_start:type_line_start + 80]

    for invalid_example in ("bug", "insight", "pattern"):
        assert invalid_example not in type_line, (
            f"help text mentions {invalid_example!r}, which isn't in TYPES={sorted(TYPES)}"
        )
