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
    assert _run_cli("init", "--repo", str(repo)).returncode == 0


def _record(repo, statement="a fact", type="fact", scope="repo", confidence="low", extra=None):
    args = [
        "record", "--repo", str(repo), "--type", type, "--scope", scope,
        "--statement", statement, "--confidence", confidence, "--json",
    ]
    if extra:
        args += extra
    result = _run_cli(*args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["id"]


def test_cli_status_transition_round_trip(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo, statement="an experiment", type="experiment")

    result = _run_cli(
        "status", str(memory_id), "abandon", "--repo", str(repo),
        "--reason", "ran out of time",
    )
    assert result.returncode == 0
    assert "-> abandoned" in result.stdout


def test_cli_status_illegal_transition_exits_1(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)  # starts provisional
    abandon = _run_cli("status", str(memory_id), "abandon", "--repo", str(repo), "--reason", "x")
    assert abandon.returncode == 0
    archive = _run_cli("status", str(memory_id), "archive", "--repo", str(repo), "--reason", "x")
    assert archive.returncode == 0
    # archived is terminal -- nothing is a legal target from it
    result = _run_cli("status", str(memory_id), "activate", "--repo", str(repo), "--reason", "x")
    assert result.returncode == 1
    assert "cannot transition" in result.stderr


def test_cli_status_missing_reason_exits_2(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)
    result = _run_cli("status", str(memory_id), "abandon", "--repo", str(repo))
    assert result.returncode == 2


def test_cli_evidence_add_and_verify(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)

    add_result = _run_cli(
        "evidence", "add", str(memory_id), "--repo", str(repo),
        "--kind", "test_output", "--description", "ran the load test, it failed",
        "--command", "pytest -k load", "--expected", "fails with TimeoutError",
        "--json",
    )
    assert add_result.returncode == 0
    evidence_id = json.loads(add_result.stdout)["evidence_id"]

    show_result = _run_cli("show", str(memory_id), "--repo", str(repo))
    assert "active" in show_result.stdout  # promoted from provisional

    verify_result = _run_cli("evidence", "verify", str(evidence_id), "--repo", str(repo), "--json")
    assert verify_result.returncode == 0
    payload = json.loads(verify_result.stdout)
    assert payload["command"] == "pytest -k load"


def test_cli_link_contradicts(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    a = _record(repo, statement="X is true")
    b = _record(repo, statement="X is false")

    result = _run_cli("link", str(a), "contradicts", str(b), "--repo", str(repo))
    assert result.returncode == 0

    show_result = _run_cli("show", str(a), "--repo", str(repo), "--json")
    payload = json.loads(show_result.stdout)
    assert any(link["link_type"] == "contradicts" for link in payload["links"])


def test_cli_link_self_link_exits_1(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)
    result = _run_cli("link", str(memory_id), "contradicts", str(memory_id), "--repo", str(repo))
    assert result.returncode == 1


def test_cli_search_round_trip(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record(repo, statement="scanner batching detail")

    result = _run_cli("search", "--repo", str(repo), "--query", "scanner batching", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["matched"] == 1


def test_cli_record_update_path(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo, extra=["--path", "src/fixture_a/scanner.py"])

    subprocess.run(["git", "mv", "src/fixture_a/scanner.py", "src/fixture_a/batch_scanner.py"],
                    cwd=repo, check=True, capture_output=True)
    (repo / "src" / "fixture_a" / "batch_scanner.py").write_text("def scan_batch(): return 999\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "rename+edit"], cwd=repo, check=True, capture_output=True)

    result = _run_cli(
        "record", str(memory_id), "--update-path", "--repo", str(repo),
        "--old-path", "src/fixture_a/scanner.py", "--new-path", "src/fixture_a/batch_scanner.py",
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["paths"][0]["path"] == "src/fixture_a/batch_scanner.py"


def test_cli_record_add_path(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)

    result = _run_cli(
        "record", str(memory_id), "--add-path", "src/fixture_a/scanner.py",
        "--repo", str(repo), "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["paths"][0]["path"] == "src/fixture_a/scanner.py"


def test_cli_record_add_path_text_output(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)

    result = _run_cli(
        "record", str(memory_id), "--add-path", "src/fixture_a/scanner.py",
        "--repo", str(repo),
    )
    assert result.returncode == 0
    assert f"Added path to memory {memory_id}" in result.stdout
    assert "src/fixture_a/scanner.py" in result.stdout


def test_cli_record_add_path_missing_id_exits_2(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    result = _run_cli(
        "record", "--add-path", "src/fixture_a/scanner.py", "--repo", str(repo),
    )
    assert result.returncode == 2
    assert "ID is required" in result.stderr


def test_cli_record_add_path_rejects_dead_path(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    memory_id = _record(repo)

    result = _run_cli(
        "record", str(memory_id), "--add-path", "no/such/file.py", "--repo", str(repo),
    )
    assert result.returncode == 1
    assert "does not exist at HEAD" in result.stderr


def test_cli_list_needs_consolidation_and_abandoned_without_lesson(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record(repo, statement="Scanner batches items in groups of fifty for the shared host.")
    _record(repo, statement="Scanner batches items in groups of fifty for shared hosts.")

    result = _run_cli("list", "--repo", str(repo), "--needs-consolidation", "--json")
    assert result.returncode == 0
    assert len(json.loads(result.stdout)) == 2

    abandoned_id = _record(repo, statement="a forgotten experiment", type="experiment")
    _run_cli("status", str(abandoned_id), "abandon", "--repo", str(repo), "--reason", "no time")

    result = _run_cli("list", "--repo", str(repo), "--abandoned-without-lesson", "--json")
    payload = json.loads(result.stdout)
    assert {m["id"] for m in payload} == {abandoned_id}


def test_cli_show_explain_against(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    _record(repo, statement="Scanner batches at fifty items because of host timeouts.", type="decision", confidence="high")

    result = _run_cli(
        "show", "1", "--repo", str(repo), "--explain-against", "scanner batches fifty",
    )
    assert result.returncode == 0
    assert "explain:" in result.stdout
    assert "total=" in result.stdout


def test_cli_record_lesson_from(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)
    experiment_id = _record(repo, statement="tried a caching layer", type="experiment")
    _run_cli("status", str(experiment_id), "abandon", "--repo", str(repo), "--reason", "too slow")

    lesson_id = _record(
        repo, statement="Do not add a caching layer here; it made things slower.",
        type="lesson", confidence="high",
        extra=["--lesson-from", str(experiment_id)],
    )

    show_result = _run_cli("show", str(lesson_id), "--repo", str(repo), "--json")
    payload = json.loads(show_result.stdout)
    assert any(link["link_type"] == "lesson_from" for link in payload["links"])
