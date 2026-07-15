"""Stage 10 exit criterion: attach/verify round-trip against a real HTTP
server (Python's http.server, not a mocked urllib call) plus graceful
degradation when the API is unreachable, no git remote is configured, or
Gitea is left unconfigured entirely (the default, covered already in
test_evidence.py's test_verify_evidence_gitea_backed_degrades_to_unverifiable_when_unconfigured).
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from robo_cortex.core.db import connect, migrate
from robo_cortex.core.evidence import attach_evidence, verify_evidence
from robo_cortex.core.memory import record_memory

from .fixtures import add_remote, build_fixture_repo_a


class _GiteaMockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/v1/repos/acme/widgets/pulls/88":
            self._json(200, {
                "state": "closed", "merged": True,
                "title": "Fix batch timeout", "html_url": "http://mock/pulls/88",
            })
        elif self.path == "/api/v1/repos/acme/widgets/issues/12":
            self._json(200, {
                "state": "open", "title": "Investigate timeout",
                "html_url": "http://mock/issues/12",
            })
        else:
            self._json(404, {"message": "not found"})

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 -- BaseHTTPRequestHandler's signature
        pass  # keep test output quiet


@pytest.fixture
def gitea_mock_server():
    server = HTTPServer(("127.0.0.1", 0), _GiteaMockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def _unused_port() -> int:
    """A port nothing is listening on, for the unreachable-API test --
    binding and immediately closing guarantees it's free at bind time,
    unlike a hardcoded port number that might collide on a shared host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _store(tmp_path):
    repo = build_fixture_repo_a(tmp_path)
    conn = connect(tmp_path / "memory.db")
    migrate(conn)
    return repo, conn


def test_verify_evidence_gitea_pr_verified_round_trip(tmp_path, gitea_mock_server, monkeypatch):
    monkeypatch.setenv("ROBO_CORTEX_GITEA_URL", gitea_mock_server)
    repo, conn = _store(tmp_path)
    add_remote(repo, "https://mock.example/acme/widgets.git")

    result = record_memory(conn, repo, type="decision", scope="repo", statement="x", confidence="high")
    attach = attach_evidence(conn, repo, result["id"], kind="gitea_pr", description="fixed in PR", ref="pr:88")

    verified = verify_evidence(conn, attach["evidence_id"], repo)

    assert verified["status"] == "verified"
    assert verified["merged"] is True
    assert verified["title"] == "Fix batch timeout"
    assert verified["html_url"] == "http://mock/pulls/88"
    assert "checked_at" in verified


def test_verify_evidence_gitea_issue_verified_round_trip(tmp_path, gitea_mock_server, monkeypatch):
    monkeypatch.setenv("ROBO_CORTEX_GITEA_URL", gitea_mock_server)
    repo, conn = _store(tmp_path)
    add_remote(repo, "git@mock.example:acme/widgets.git")  # SSH remote form

    result = record_memory(conn, repo, type="fact", scope="repo", statement="x", confidence="low")
    attach = attach_evidence(conn, repo, result["id"], kind="gitea_issue", description="tracked", ref="issue:12")

    verified = verify_evidence(conn, attach["evidence_id"], repo)

    assert verified["status"] == "verified"
    assert verified["state"] == "open"
    assert verified["title"] == "Investigate timeout"


def test_verify_evidence_gitea_degrades_when_api_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBO_CORTEX_GITEA_URL", f"http://127.0.0.1:{_unused_port()}")
    repo, conn = _store(tmp_path)
    add_remote(repo, "https://mock.example/acme/widgets.git")

    result = record_memory(conn, repo, type="decision", scope="repo", statement="x", confidence="high")
    attach = attach_evidence(conn, repo, result["id"], kind="gitea_pr", description="fixed in PR", ref="pr:88")

    verified = verify_evidence(conn, attach["evidence_id"], repo)

    assert verified["status"] == "unverifiable"
    assert verified["reason"] == "gitea_unreachable"


def test_verify_evidence_gitea_degrades_when_no_git_remote(tmp_path, gitea_mock_server, monkeypatch):
    monkeypatch.setenv("ROBO_CORTEX_GITEA_URL", gitea_mock_server)
    repo, conn = _store(tmp_path)  # fixture repo has no remote configured

    result = record_memory(conn, repo, type="decision", scope="repo", statement="x", confidence="high")
    attach = attach_evidence(conn, repo, result["id"], kind="gitea_pr", description="fixed in PR", ref="pr:88")

    verified = verify_evidence(conn, attach["evidence_id"], repo)

    assert verified["status"] == "unverifiable"
    assert verified["reason"] == "gitea_unreachable"


def test_verify_evidence_gitea_degrades_when_repo_root_not_given(tmp_path, gitea_mock_server, monkeypatch):
    """Even when Gitea is configured and reachable, omitting repo_root (the
    CLI/MCP callers always pass it; this exercises the core function's own
    default) degrades the same as being unconfigured -- no repo context
    means no owner/repo to resolve."""
    monkeypatch.setenv("ROBO_CORTEX_GITEA_URL", gitea_mock_server)
    repo, conn = _store(tmp_path)
    add_remote(repo, "https://mock.example/acme/widgets.git")

    result = record_memory(conn, repo, type="decision", scope="repo", statement="x", confidence="high")
    attach = attach_evidence(conn, repo, result["id"], kind="gitea_pr", description="fixed in PR", ref="pr:88")

    verified = verify_evidence(conn, attach["evidence_id"])  # repo_root omitted

    assert verified["status"] == "unverifiable"
    assert verified["reason"] == "gitea_not_configured"


def test_verify_evidence_gitea_pr_not_found_degrades_gracefully(tmp_path, gitea_mock_server, monkeypatch):
    """A rotted reference (PR number the mock server doesn't recognize, i.e.
    a 404) degrades the same as any other unreachable/failed request rather
    than raising -- evidence can rot without crashing the core."""
    monkeypatch.setenv("ROBO_CORTEX_GITEA_URL", gitea_mock_server)
    repo, conn = _store(tmp_path)
    add_remote(repo, "https://mock.example/acme/widgets.git")

    result = record_memory(conn, repo, type="decision", scope="repo", statement="x", confidence="high")
    attach = attach_evidence(conn, repo, result["id"], kind="gitea_pr", description="rotted", ref="pr:999")

    verified = verify_evidence(conn, attach["evidence_id"], repo)

    assert verified["status"] == "unverifiable"
    assert verified["reason"] == "gitea_unreachable"
