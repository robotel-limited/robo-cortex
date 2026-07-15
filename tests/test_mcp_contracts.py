"""Stage 9 exit criterion: each tool's inputs/outputs/failure behavior match
MCP_TOOLS.md. Drives the real server subprocess with the real client SDK
(mcp.client.stdio.stdio_client + mcp.ClientSession) -- no hand-rolled
JSON-RPC, same as the stdout-purity tests.
"""

import json
import os
import subprocess
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .fixtures import build_fixture_repo_a


def _init(repo):
    subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", "init", "--repo", str(repo)],
        check=True, capture_output=True,
    )


def _server_params(repo):
    # env=dict(os.environ), not the default: StdioServerParameters only
    # inherits a curated safe-var allowlist otherwise (a deliberate SDK
    # security feature -- a real client shouldn't leak its whole environment
    # to a spawned server by default). That allowlist does not include
    # ROBO_CORTEX_GLOBAL_DB, so without this the spawned server silently
    # fell back to the real ~/.cortex/global.db instead of the per-test
    # tmp_path override -- caught by inspecting the real path after a test
    # run and finding it non-empty, not by any assertion in this file.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "robo_cortex.cli", "mcp", "--repo", str(repo)],
        env=dict(os.environ),
    )


def _unwrap(result):
    """A successful call's payload is JSON text inside the first content
    block (dict return values aren't declared as structured-output models,
    so FastMCP serializes them as text -- same shape the CLI's --json
    already produces). Raises AssertionError with the tool's own error
    message on isError, so a failing assertion is legible without a debugger.
    """
    if result.isError:
        text = result.content[0].text if result.content else "(no content)"
        raise AssertionError(f"tool call returned isError=True: {text}")
    return json.loads(result.content[0].text)


async def _run_scenario(repo, scenario):
    """scenario: async def f(session) -> Any. One subprocess, one session,
    for every call the scenario makes -- so a test that records and then
    retrieves in the same test sees its own write."""
    async with stdio_client(_server_params(repo)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await scenario(session)


def run_scenario(repo, scenario):
    return anyio.run(_run_scenario, repo, scenario)


async def _call(session, tool_name, arguments):
    return _unwrap(await session.call_tool(tool_name, arguments))


async def _call_expect_error(session, tool_name, arguments):
    result = await session.call_tool(tool_name, arguments)
    assert result.isError, f"expected {tool_name} to fail, got: {result}"
    return result.content[0].text if result.content else ""


def test_list_tools_matches_mcp_tools_md(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        return await session.list_tools()

    result = run_scenario(repo, scenario)
    names = {tool.name for tool in result.tools}
    assert names == {
        "retrieve_context", "record_memory", "attach_evidence", "get_memory",
        "change_status", "search_memory", "list_affected", "verify_evidence",
    }


def test_tool_descriptions_carry_data_not_instructions_framing(tmp_path):
    """The security posture requirement (ARCHITECTURE.md §10): every tool
    description that returns memory content states it's data, not
    instructions. Checked structurally against the live server, not just by
    reading the source that generates it."""
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        return await session.list_tools()

    result = run_scenario(repo, scenario)
    by_name = {tool.name: (tool.description or "") for tool in result.tools}

    for name in ("retrieve_context", "get_memory", "search_memory"):
        assert "data, not instructions" in by_name[name] or "not instructions" in by_name[name], (
            f"{name} description missing the data-not-instructions framing: {by_name[name]!r}"
        )
    for name in ("attach_evidence", "get_memory", "verify_evidence"):
        assert "review it before running" in by_name[name].lower() or "not an instruction" in by_name[name].lower(), (
            f"{name} description missing the command-is-data framing: {by_name[name]!r}"
        )


def test_record_memory_then_get_memory_round_trip(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        record_result = await _call(session, "record_memory", {
            "type": "decision", "scope": "repo", "confidence": "high",
            "statement": "Scanner batches at 50 items via MCP.",
            "paths": ["src/fixture_a/scanner.py"],
        })
        fetched = await _call(session, "get_memory", {"memory_id": record_result["id"]})
        return record_result, fetched

    record_result, fetched = run_scenario(repo, scenario)
    assert record_result["status"] == "provisional"
    assert fetched["statement"] == "Scanner batches at 50 items via MCP."
    assert fetched["paths"][0]["path"] == "src/fixture_a/scanner.py"


def test_record_memory_dead_path_fails_loudly(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        return await _call_expect_error(session, "record_memory", {
            "type": "fact", "scope": "repo", "confidence": "low",
            "statement": "links nowhere", "paths": ["no/such/file.py"],
        })

    message = run_scenario(repo, scenario)
    assert "does not exist at HEAD" in message


def test_record_memory_scope_global_requires_assumptions(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        rejected = await _call_expect_error(session, "record_memory", {
            "type": "lesson", "scope": "global", "confidence": "high",
            "statement": "a lesson with no assumptions",
        })
        accepted = await _call(session, "record_memory", {
            "type": "lesson", "scope": "global", "confidence": "high",
            "statement": "a lesson with assumptions",
            "assumptions": "single-user, local-first",
        })
        return rejected, accepted

    rejected, accepted = run_scenario(repo, scenario)
    assert "require non-empty assumptions" in rejected
    assert accepted["status"] == "provisional"


def test_attach_evidence_promotes_provisional_to_active(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        record_result = await _call(session, "record_memory", {
            "type": "fact", "scope": "repo", "confidence": "low", "statement": "x",
        })
        evidence_result = await _call(session, "attach_evidence", {
            "memory_id": record_result["id"], "kind": "free_text",
            "description": "confirmed by reading the code",
        })
        fetched = await _call(session, "get_memory", {"memory_id": record_result["id"]})
        return evidence_result, fetched

    evidence_result, fetched = run_scenario(repo, scenario)
    assert evidence_result["memory_evidence_strength"] == 0.4
    assert fetched["status"] == "active"


def test_retrieve_context_always_includes_score_breakdown(tmp_path):
    """MCP_TOOLS.md: the MCP tool always includes score_breakdown per item
    (no --explain-equivalent input needed, unlike the CLI)."""
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        await _call(session, "record_memory", {
            "type": "decision", "scope": "repo", "confidence": "high",
            "statement": "Scanner batches at fifty items.",
        })
        return await _call(session, "retrieve_context", {"task": "scanner batches fifty"})

    result = run_scenario(repo, scenario)
    assert result["meta"]["matched"] == 1
    assert "score_breakdown" in result["data"][0]
    assert set(result["data"][0]["score_breakdown"]) >= {
        "text_match", "path_overlap", "confidence", "evidence", "status", "recency", "total",
    }


def test_change_status_transition_and_illegal_transition(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        record_result = await _call(session, "record_memory", {
            "type": "experiment", "scope": "repo", "confidence": "low", "statement": "x",
        })
        abandoned = await _call(session, "change_status", {
            "memory_id": record_result["id"], "new_status": "abandoned", "reason": "ran out of time",
        })
        illegal = await _call_expect_error(session, "change_status", {
            "memory_id": record_result["id"], "new_status": "active", "reason": "x",
        })
        return abandoned, illegal

    abandoned, illegal = run_scenario(repo, scenario)
    assert abandoned["status"] == "abandoned"
    assert "cannot transition" in illegal


def test_search_memory(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        await _call(session, "record_memory", {
            "type": "fact", "scope": "repo", "confidence": "low",
            "statement": "scanner batching detail",
        })
        return await _call(session, "search_memory", {"query": "scanner batching"})

    result = run_scenario(repo, scenario)
    assert result["matched"] == 1


def test_list_affected(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        await _call(session, "record_memory", {
            "type": "decision", "scope": "repo", "confidence": "high",
            "statement": "Scanner batches at 50 items.",
            "paths": ["src/fixture_a/scanner.py"],
        })
        return await _call(session, "list_affected", {})

    (repo / "src" / "fixture_a" / "scanner.py").write_text("def scan_batch(): pass\n")
    result = run_scenario(repo, scenario)
    assert result["matched"] == 1
    assert "path_changed" in result["data"][0]["reason"]


def test_verify_evidence_command_backed(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        record_result = await _call(session, "record_memory", {
            "type": "fact", "scope": "repo", "confidence": "low", "statement": "x",
        })
        evidence_result = await _call(session, "attach_evidence", {
            "memory_id": record_result["id"], "kind": "test_output",
            "description": "ran it", "command": "pytest -k batch_size",
            "expected_outcome": "fails at 200",
        })
        return await _call(session, "verify_evidence", {"evidence_id": evidence_result["evidence_id"]})

    result = run_scenario(repo, scenario)
    assert result["command"] == "pytest -k batch_size"
    assert "review it before running" in result["note"].lower()


def test_verify_evidence_gitea_backed_degrades_gracefully(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        record_result = await _call(session, "record_memory", {
            "type": "decision", "scope": "repo", "confidence": "high", "statement": "x",
        })
        evidence_result = await _call(session, "attach_evidence", {
            "memory_id": record_result["id"], "kind": "gitea_pr",
            "description": "fixed in PR", "ref": "pr:88",
        })
        return await _call(session, "verify_evidence", {"evidence_id": evidence_result["evidence_id"]})

    result = run_scenario(repo, scenario)
    assert result["status"] == "unverifiable"
    assert result["reason"] == "gitea_not_configured"


def test_scope_disambiguator_reaches_shadowed_global_memory(tmp_path):
    """The second pre-Stage-9 fix, verified all the way through the MCP
    layer: a local id 1 shadows global id 1 by default; scope='global'
    reaches the intended memory."""
    repo = build_fixture_repo_a(tmp_path)
    _init(repo)

    async def scenario(session):
        local_result = await _call(session, "record_memory", {
            "type": "fact", "scope": "repo", "confidence": "low", "statement": "a local fact",
        })
        global_result = await _call(session, "record_memory", {
            "type": "lesson", "scope": "global", "confidence": "high",
            "statement": "a global lesson", "assumptions": "single-user",
        })
        assert local_result["id"] == global_result["id"]

        default_fetch = await _call(session, "get_memory", {"memory_id": local_result["id"]})
        repo_fetch = await _call(session, "get_memory", {"memory_id": local_result["id"], "scope": "repo"})
        global_fetch = await _call(session, "get_memory", {"memory_id": global_result["id"], "scope": "global"})
        return default_fetch, repo_fetch, global_fetch

    default_fetch, repo_fetch, global_fetch = run_scenario(repo, scenario)
    assert default_fetch["statement"] == "a local fact"  # default shadows to local
    assert repo_fetch["statement"] == "a local fact"
    assert global_fetch["statement"] == "a global lesson"
