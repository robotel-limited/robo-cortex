# Contributing to robo-cortex

Thanks for considering a contribution. This project is intentionally small and dependency-light — keep that in mind when proposing changes.

## Development setup

```bash
git clone <this repository's URL>
cd robo-cortex
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

`.[dev]` pulls in `pytest` and the optional `mcp` extra, so the full test suite (including MCP server tests) can run.

## Running the tests

```bash
python3 -m pytest tests/
```

The suite runs against real fixture git repositories (`tests/fixtures.py`), not mocks — most tests drive the actual CLI as a subprocess or call `robo_cortex.core` functions directly against a real SQLite file. Every test's `ROBO_CORTEX_GLOBAL_DB` is redirected to an isolated tmp path automatically (`tests/conftest.py`), so nothing touches your real `~/.cortex/global.db`.

Before opening a PR, the full suite should pass:

```bash
python3 -m pytest tests/ -q
```

## Ground rules

- **Every bug fix needs a regression test.** Write the test first if you can — it's the cheapest way to prove the fix actually fixes the reported behavior, not just something adjacent to it.
- **No comments explaining *what* the code does.** Code should be legible from naming; a comment earns its place only when it explains a non-obvious *why* (a constraint, an invariant, a workaround for a specific bug). Several existing files (`core/invalidate.py`, `core/evidence.py`, `gitea.py`) are worth reading as examples of the style this project wants.
- **Don't add a dependency without a reason in the commit message.** The core CLI is stdlib + SQLite only; the `mcp` extra is the one deliberate exception (`pyproject.toml` documents why). New third-party dependencies should be rare and justified.
- **Keep the CLI, SDK, and MCP tool surface behaviorally consistent.** All three call the same `robo_cortex.core` functions — if you fix a bug in one entry point, check whether the other two need the same fix (this project has a whole audit trail of exactly that kind of mismatch).
- **Match the existing test style.** Most CLI-level tests use a `_run_cli()` subprocess helper (see any `tests/test_cli_*.py`); most core-level tests build a fixture repo via `tests/fixtures.py` and call `robo_cortex.core` functions directly. Pick whichever matches what you're testing.

## Reporting bugs / requesting features

Open a GitHub issue. For bugs, include:
- The exact command(s) run and their full output (stdout + stderr).
- Your Python version and OS.
- Whether `.cortex/memory.db` and/or `~/.cortex/global.db` are involved.

For anything that might be a security issue, see [SECURITY.md](SECURITY.md) instead — please don't file it as a public issue.

## Pull requests

- Keep PRs focused — one fix or feature per PR is easier to review than a bundle.
- Reference the issue it fixes, if any.
- CI (GitHub Actions, `.github/workflows/ci.yml`) runs the full test suite on Python 3.11–3.13; it needs to pass before merge.
