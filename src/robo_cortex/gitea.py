"""Gitea integration: the optional evidence layer (ARCHITECTURE.md §9).

A single module, called only from `core.evidence.verify_evidence` for
`gitea_pr`/`gitea_issue` evidence -- never from `record`, `retrieve`, or any
other core read/write path. The memory core works identically with this
module entirely unconfigured (the MVP default) or unreachable.

Endpoint paths, auth header format, and response fields verified against
Gitea's own published API docs (docs.gitea.com/api/1.20, docs.gitea.com/
development/api-usage) before writing this file, not invented:
- base path `/api/v1/`
- token auth via `Authorization: token <TOKEN>` (Gitea's own documented
  wording: "for historical reasons... the word `token` included before
  the API key")
- `GET /repos/{owner}/{repo}/pulls/{index}` and `.../issues/{index}`
- PullRequest objects carry `state`, `merged`, `title`, `html_url`;
  Issue objects carry `state`, `title`, `html_url`
"""

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

GITEA_URL_ENV = "ROBO_CORTEX_GITEA_URL"
GITEA_TOKEN_ENV = "ROBO_CORTEX_GITEA_TOKEN"
GITEA_ALLOW_HTTP_ENV = "ROBO_CORTEX_GITEA_ALLOW_HTTP"
REQUEST_TIMEOUT_SECONDS = 10


class GiteaError(Exception):
    """Any failure that should degrade evidence to 'unverifiable' -- the API
    is unreachable, misconfigured, or the reference doesn't resolve to a
    repository. Never raised past verify_evidence to the caller."""


def is_configured() -> bool:
    return bool(os.environ.get(GITEA_URL_ENV))


def _is_insecure_url(url: str) -> bool:
    """Check if URL is http (not https) and not localhost."""
    if not url.startswith("http://"):
        return False
    host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
    return host not in ("localhost", "127.0.0.1", "::1")


def _base_url() -> str:
    return os.environ.get(GITEA_URL_ENV, "").rstrip("/")


def _headers() -> dict:
    headers = {"Accept": "application/json"}
    token = os.environ.get(GITEA_TOKEN_ENV)
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _owner_repo_from_remote(repo_root: Path, remote_name: str = "origin") -> tuple[str, str]:
    """Derive {owner}/{repo} from the local git remote's URL -- robo-cortex
    operates inside one repository, so the Gitea target is implied by that
    repository's own remote rather than stored redundantly per evidence row.
    Handles both SSH (git@host:owner/repo.git) and HTTPS
    (https://host/owner/repo.git) remote URL forms.
    """
    result = subprocess.run(
        ["git", "remote", "get-url", remote_name],
        cwd=repo_root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise GiteaError(f"no {remote_name!r} git remote configured in this repository")

    url = result.stdout.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]

    if "://" in url:
        path = url.split("://", 1)[1].split("/", 1)[-1]
    elif "@" in url and ":" in url:
        path = url.split(":", 1)[1]
    else:
        path = url

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        raise GiteaError(f"could not parse owner/repo from remote URL {url!r}")
    return segments[-2], segments[-1]


def _get(path: str) -> dict:
    url = f"{_base_url()}{path}"
    request = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise GiteaError(f"Gitea request to {path} failed: {error}") from error


def parse_ref(kind: str, ref: str | None) -> int:
    prefix = "pr:" if kind == "gitea_pr" else "issue:"
    if not ref or not ref.startswith(prefix):
        raise GiteaError(f"invalid ref {ref!r} for kind {kind!r}; expected {prefix}<number>")
    try:
        return int(ref[len(prefix):])
    except ValueError as error:
        raise GiteaError(f"invalid ref {ref!r}: not a number after {prefix!r}") from error


def check_pull_request(repo_root: Path, pr_number: int) -> dict:
    base_url = _base_url()
    if _is_insecure_url(base_url) and not os.environ.get(GITEA_ALLOW_HTTP_ENV):
        raise GiteaError("gitea_insecure_url: http URL without ROBO_CORTEX_GITEA_ALLOW_HTTP")

    owner, repo = _owner_repo_from_remote(repo_root)
    data = _get(f"/api/v1/repos/{owner}/{repo}/pulls/{pr_number}")
    return {
        "state": data.get("state"),
        "merged": bool(data.get("merged", False)),
        "title": data.get("title"),
        "html_url": data.get("html_url"),
    }


def check_issue(repo_root: Path, issue_number: int) -> dict:
    base_url = _base_url()
    if _is_insecure_url(base_url) and not os.environ.get(GITEA_ALLOW_HTTP_ENV):
        raise GiteaError("gitea_insecure_url: http URL without ROBO_CORTEX_GITEA_ALLOW_HTTP")

    owner, repo = _owner_repo_from_remote(repo_root)
    data = _get(f"/api/v1/repos/{owner}/{repo}/issues/{issue_number}")
    return {
        "state": data.get("state"),
        "title": data.get("title"),
        "html_url": data.get("html_url"),
    }
