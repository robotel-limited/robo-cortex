# Security Policy

## Supported versions

Only the latest released minor version receives security fixes. Given the project's size and stage, there is no separate long-term-support branch.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a suspected security vulnerability.

Instead, report it privately:
- Preferred: use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) on this repository (Security tab → "Report a vulnerability").
- Alternative: email **tech@robotel.top** with a description of the issue and, if possible, steps to reproduce.

We aim to acknowledge reports within a few business days. Once a fix is available, we'll credit the reporter in the release notes unless you'd prefer to stay anonymous.

## What's in scope

robo-cortex runs entirely locally: SQLite files under `.cortex/` (repo-scoped) and `~/.cortex/` (global-scoped), no network calls unless Gitea evidence verification is explicitly configured (`ROBO_CORTEX_GITEA_URL`). Relevant categories:
- SQL injection or other query-construction issues in `robo_cortex.core`.
- Command injection in any `subprocess` call (git, Gitea).
- Path traversal or unsafe file handling (export/import, evidence attachments, cold storage).
- Anything in the MCP tool surface that could let untrusted tool-call input escape its intended data boundary.

## Threat model: cross-project memory channel

robo-cortex's global store (`~/.cortex/global.db`) is a shared knowledge base across all projects on a machine. This is intentional — reusable lessons (browser bugs, language patterns, framework best practices) cross projects. But it creates an implicit channel between repositories:

**Risk**: if one project's agent is compromised (via prompt injection, a malicious dependency, untrusted tool input), it can record "lessons" to the global store that will be retrieved and suggested in another project. These suggestions carry the stated confidence and evidence, which (per the "data, not instructions" framing in `MCP_TOOLS.md`) should be *reviewed*, not executed — but in a high-volume scenario with many memories, this is a social engineering vector.

**Mitigations**:
- `assumptions` gate on scope-B (global) memories: a broad query like "test" won't retrieve a global memory unless the memory's assumptions text overlaps the query. This raises the bar for accidental cross-project suggestion.
- Explicit framing in MCP tool descriptions: returned memory content is data carrying a stated confidence and evidence, not a directive.
- `ROBO_CORTEX_NO_GLOBAL` environment variable disables the global store entirely (CLI and MCP both skip opening it), for anyone who wants strict per-project isolation.

This is not a solved problem — it is a known trade-off. The global store is valuable for reusing lessons, and the assumptions gate reduces noise, but in a fully adversarial scenario (a compromised agent with `roco` command access), using `NO_GLOBAL=1` is the right choice.
- Memories are stored **in plaintext** in local SQLite files. This is by design (the file is meant to be inspectable with plain `sqlite3`), not a bug — but it means **you should not record secrets, credentials, or API keys as memory statements or evidence**. An agent recording "the staging API key is X" as a lesson is a real, avoidable risk; treat robo-cortex's store the same way you'd treat a shell history file or a `.env` committed by mistake — worth keeping out of version control (`.cortex/` is `.gitignore`d by `roco init`) but not a place for secrets in the first place.
