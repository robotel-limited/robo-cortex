"""Stage 9 exit criterion: start `robo-cortex mcp` as a subprocess; the
first bytes on stdout are JSON-RPC, never a banner or log line.
"""

import json
import select
import subprocess
import sys

import mcp.types as types

from .fixtures import build_fixture_repo_a


def _initialize_request_line() -> str:
    """Built from the SDK's own model classes (mcp.types), not hand-rolled
    JSON -- the wire shape is whatever the installed SDK actually expects."""
    request = types.JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params={
            "protocolVersion": types.LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        },
    )
    return types.JSONRPCMessage(request).model_dump_json(by_alias=True, exclude_none=True) + "\n"


def _readline_with_timeout(stream, timeout: float) -> str:
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise TimeoutError(f"no output on stdout within {timeout}s")
    return stream.readline()


def test_mcp_stdout_first_bytes_are_json_rpc(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", "init", "--repo", str(repo)],
        check=True, capture_output=True,
    )

    proc = subprocess.Popen(
        [sys.executable, "-m", "robo_cortex.cli", "mcp", "--repo", str(repo)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        proc.stdin.write(_initialize_request_line())
        proc.stdin.flush()

        first_line = _readline_with_timeout(proc.stdout, timeout=10)
        assert first_line, "no output on stdout at all"

        # If a banner/log line had been printed before the response (e.g. by
        # a startup log statement or a stray print), this would be it, and
        # json.loads would fail on it -- exactly the failure this test exists
        # to catch. A clean parse with a jsonrpc field is the actual bar.
        payload = json.loads(first_line)
        assert payload.get("jsonrpc") == "2.0"
        assert "result" in payload or "error" in payload
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_mcp_refuses_uninitialized_repo_without_stdout_output(tmp_path):
    """NotInitializedError fires before any MCP session starts (during repo/
    store resolution in build_server, ahead of server.run()) -- must report
    on stderr with nothing on stdout, same purity guarantee even on failure."""
    not_a_robo_cortex_repo = tmp_path / "plain-git-repo"
    not_a_robo_cortex_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=not_a_robo_cortex_repo, check=True)

    result = subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", "mcp", "--repo", str(not_a_robo_cortex_repo)],
        capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "init" in result.stderr.lower()
