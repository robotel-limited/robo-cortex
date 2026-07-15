# robo-cortex

**A git-aware, evidence-based memory store for AI coding agents.**

Your AI agent debugs a bug, learns the lesson, and forgets it by next week — or worse, keeps citing a "lesson" that the code has since made false. robo-cortex is a local knowledge base built for that specific failure mode: memories are anchored to git blob hashes, so when the code they're about changes, the memory is automatically flagged for review instead of being silently trusted or silently lost.

---

## Why robo-cortex, not another memory tool

Most agent-memory tools are embeddings + a vector database + a cloud dependency. robo-cortex is deliberately none of that. Four things it does that a generic key-value memory store doesn't:

1. **Git-aware staleness detection.** Every memory can link to specific file paths, captured by git blob hash at record time. When the linked code changes, the memory is automatically flagged `needs_review` on the next `retrieve`/`search`/`affected` call — and a committed revert automatically heals it back. The healing requires three conditions: (a) the revert must be **committed** (git blob hash must match HEAD again), (b) the memory must have been flagged by the system (not manually via `change_status`), and (c) you must run a lazy trigger (`retrieve`/`search`/`affected`) after the revert to scan for changes. No other memory tool ties itself to your actual code's history this way.
2. **Evidence, not vibes.** Memories can carry attached evidence (test output, a commit, a re-runnable command) with a mechanically computed strength — not a judgment call. A `provisional` memory only becomes `active` once real evidence backs it, or a human explicitly promotes it.
3. **Zero dependencies, fully local.** Pure stdlib + SQLite (FTS5 for search). No embeddings, no API keys, no network calls unless you explicitly configure Gitea evidence verification. `.cortex/memory.db` is just a file — inspect it with `sqlite3` any time.
4. **A real lifecycle with an audit trail.** Every status change (`active` → `superseded` → `archived`, etc.) requires a `--reason`, permanently recorded. Nothing disappears silently; wrong lessons are marked `invalidated`, not deleted.

## Pilot measurement (informative, not definitive)

A small, real evaluation pilot (3 runs per arm, **one task only**) measured **2.7% fewer tokens and 10.6% less wall-clock time** with robo-cortex versus without, at equal fix quality. This is a real but modest signal from a limited sample — see [EVALUATION.md](https://github.com/robotel-limited/robo-cortex/blob/main/EVALUATION.md) §9 for full methodology and caveats. Key limitations: n=3/arm (too small to generalize), one task type (may not represent typical workloads), and token-accounting asymmetry (doesn't credit avoided re-debugging when a stale lesson is caught before being retried, which is the real value proposition). We'd rather publish a modest number we measured than a dramatic one we didn't. **Not a benchmark** — a proof of concept that robo-cortex doesn't hurt wall-clock time in a realistic scenario, and may help on tokens. Definitive performance claims await a larger study across more task types.

---

## Quick Start

**Prerequisite:** robo-cortex requires a git repository (staleness detection needs git history to compare against):
```bash
git init && git add -A && git commit -m "initial commit"
```

### Installation

```bash
pip install robo-cortex
```

If `pip install` refuses with `error: externally-managed-environment` (common on recent Debian/Ubuntu), use a virtual environment or `pipx`:
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install robo-cortex
# or: pipx install robo-cortex
```

If you plan to use robo-cortex with an MCP-capable agent (Claude Desktop/Code, etc.), install the MCP extra instead:
```bash
pip install 'robo-cortex[mcp]'
```

### Usage

```bash
cd /path/to/your/project
roco init

# Record a project-specific lesson (scope=repo: no extra fields needed)
roco record --type lesson --scope repo \
  --statement "Copy-to-clipboard fails on HTTP; use a textarea+execCommand fallback." \
  --confidence high

# Retrieve it later
roco retrieve --task "copy to clipboard http"
```

```
matched=1 returned=1 needs_review=0 contradicted=0
[1] score=0.650 repo   lesson       Copy-to-clipboard fails on HTTP; use a textarea+execCommand fallback.
```

`--path` links a memory to a file, but only accepts a path that already exists at HEAD (no memory is ever born pointing at a dead link). For code you just wrote but haven't committed yet: record the memory without `--path` now, commit, then attach the path afterward:

```bash
roco record --type decision --scope repo --statement "..." --confidence high
# id=7, no linked path yet

git add new_module.py && git commit -m "add new_module.py"
roco record 7 --add-path new_module.py
```

Reusable lessons (not specific to this project) use `scope=global` and require `--assumptions` — the conditions under which the lesson applies, so it doesn't get suggested everywhere by accident:

```bash
roco record --type lesson --scope global \
  --statement "Safari 14 breaks CSS grid+gap. Use flexbox+margin instead." \
  --confidence high \
  --assumptions "css grid gap safari"
```

### Enable enforcement (recommended)

```bash
roco hooks install
```

Installs a git pre-commit hook: if the commit touches code linked to a memory that's `active`/`provisional`/`needs_review`, the commit is blocked with the memory's id and a review prompt, until you've reviewed it or bypassed explicitly. Example, for a memory linked to `src/scanner.py` when that file is part of the commit:

```
robo-cortex: this commit touches code linked to memories that need review:
  [1] path_changed:src/scanner.py@working_tree  scanner batches at 50 items deliberately

Review with: roco show <id>
Then either re-verify (roco status <id> activate --reason "...") or supersede it, and commit again.
To bypass this check: git commit --no-verify
```

The bypass is real and documented — `git commit --no-verify` skips it, same as any git hook. This is "enforcement by default, bypass explicit," not "impossible to skip." See `roco hooks --help` for `uninstall`/`status`. For a CI-level check on pull requests instead of (or in addition to) local commits, see [docs/ci-example.yml](https://github.com/robotel-limited/robo-cortex/blob/main/docs/ci-example.yml).

There's also an optional post-commit hook, purely informational (it never blocks — the commit it reports on already happened by the time it runs):

```bash
roco hooks install --post-commit
```

It runs `roco affected --diff-range HEAD~1..HEAD` after each commit and reports anything at risk, so a flag shows up immediately instead of waiting for the next `retrieve`/`search`/`affected` call. `--post-commit` also works with `uninstall`/`status`, independently of the pre-commit hook.

---

## Shorthand: `roco`

Both `robo-cortex` and `roco` are identical commands (same binary, two script entry points). Use whichever fits your fingers:
```bash
roco retrieve --task "..."          # Shorter alias
robo-cortex retrieve --task "..."   # Full name, backwards compatible
```

**Name collision note:** PyPI already has an unrelated package named `roco` ("Runtime Config Generator"). If that package is also installed in the same environment, whichever was installed last wins the `roco` command — use the full `robo-cortex` name to be unambiguous, or check `roco --version` to confirm which one you're actually running.

### Shell completion

```bash
roco completion bash >> ~/.bashrc
```

Completes subcommand names and each subcommand's own flags (not flag values, and not nested sub-subcommands like `hooks install`). It's a static script generated from the installed version — re-run the command after upgrading to pick up new commands or flags.

---

## Three ways to use it

| Scenario | Best method | Why |
|----------|-------------|-----|
| One-off CLI commands (shell, scripts, manual testing) | CLI: `roco retrieve --task "..."` | Simplest, no dependencies, immediate |
| Python agent or script running your own code | Python SDK: `from robo_cortex import retrieve, record` | In-process (no subprocess), real exceptions, not string-parsed errors |
| LLM agent (Claude Code, or any MCP client) with tool-calling | MCP server: add to your MCP config | Agent decides when to call; tool descriptions ship with the package |

All three call the same underlying `robo_cortex.core` functions — pick based on what the calling code already uses.

### MCP configuration

```json
{
  "mcpServers": {
    "robo-cortex": {
      "command": "roco",
      "args": ["mcp", "--repo", "/path/to/project"]
    }
  }
}
```

Available tools: `retrieve_context`, `record_memory`, `search_memory`, `attach_evidence`, `verify_evidence`, `change_status`, `get_memory`, `list_affected`. Full contract in [MCP_TOOLS.md](https://github.com/robotel-limited/robo-cortex/blob/main/MCP_TOOLS.md).

### Python SDK

```python
from robo_cortex import retrieve, record

memories = retrieve("feature description", repo_path="/srv/project")
if memories["data"]:
    print(f"Found solution: {memories['data'][0]['statement']}")

record(
    type="lesson",
    statement="What you learned",
    confidence="high",
    repo_path="/srv/project",
)
```

Full API, including the `RoboCortex` class for multiple calls against the same repo, in [PYTHON_SDK.md](https://github.com/robotel-limited/robo-cortex/blob/main/PYTHON_SDK.md).

---

## Memory Lifecycle: Status Transitions

Every memory has a status that reflects its confidence and applicability. New memories start `provisional`; manual review or evidence changes their status:

| Status | Meaning | Can transition to |
|--------|---------|-------------------|
| **provisional** | New memory, not yet validated | active, needs_review, abandoned |
| **active** | Confident, applicable to future work | needs_review, superseded, invalidated, archived, abandoned |
| **needs_review** | Suspect or context-dependent; needs human judgment | active, superseded, invalidated |
| **superseded** | Replaced by a better solution (must link to replacement ID) | archived |
| **invalidated** | Proven false or no longer applicable | archived |
| **abandoned** | Lesson that went nowhere; dead-end exploration | archived |
| **archived** | Terminal state (read-only) | — |

### Automatic Transitions

- `provisional` → `active`: happens automatically when you attach evidence to a memory (`roco evidence add`) — the first supporting data promotes the memory to trusted.

### Manual Transitions

Use `roco status <id> <verb> --reason "..."` to change status manually:

```bash
# Promote a provisional memory (no evidence yet)
roco status 5 activate --reason "Tested and validated on three projects"

# Mark a memory as superseded by a better lesson
roco status 7 supersede --supersedes 12 --reason "Version 2 of this pattern handles edge cases better"

# Mark as proven false
roco status 9 invalidate --reason "Benchmark shows this optimization actually makes things slower"

# Archive old/resolved items
roco status 3 archive --reason "No longer applicable after database migration"
```

`--reason` is mandatory and permanent — it becomes part of the memory's audit history and cannot be edited.

---

## Deciding Scope (Global vs Repo)

**Use `scope=repo`** for project-specific learnings:
- This codebase's chosen patterns (we use FastAPI + SQLAlchemy)
- Project-specific decisions (batch size tuned for our infrastructure)
- **Test:** "Does this reference our code, infra, or team decision?"

**Use `scope=global`** for reusable lessons:
- Browser/library bugs (Safari CSS, Node.js async patterns)
- Language/framework patterns
- Best practices (SQL injection prevention)

`scope=global` requires `assumptions` — the preconditions under which the lesson applies:

```json
{
  "type": "lesson",
  "scope": "global",
  "statement": "Copy-to-clipboard fails on HTTP. Use textarea + execCommand() fallback.",
  "assumptions": "Web app with clipboard feature, needs to work on HTTP",
  "confidence": "high"
}
```

---

## Sharing knowledge across projects

```bash
roco export --scope global --output kb.jsonl
# In another project:
roco import kb.jsonl
```

Import is idempotent (re-importing the same file skips duplicates by id+scope) and validated exactly like `record` — a `scope=global` line missing `assumptions`, or an invalid `type`/`confidence`, is skipped with a warning, not silently inserted or a raw database error.

Two projects that learned independently can converge with `roco merge`:
```bash
roco merge kb_a.jsonl kb_b.jsonl --output kb_merged.jsonl
# Both projects then: roco import kb_merged.jsonl
```
De-duplicates by ID+scope; conflicts resolved by confidence (higher wins), tie-broken by timestamp. See [EXPORT_IMPORT.md](https://github.com/robotel-limited/robo-cortex/blob/main/EXPORT_IMPORT.md) for the full workflow, including team-KB and backup use cases.

**Do not point `ROBO_CORTEX_GLOBAL_DB` at a network filesystem (NFS/SMB) for "shared team memory."** SQLite is not safe for concurrent writers over a network mount and can corrupt the database. Share via export/import through git instead — it's versioned and auditable, which a live-shared file isn't.

---

## FAQ

**Q: Do I need a git repository?**
A: Yes. Staleness detection, path linking, and `affected` all compare against git history. Without git, you can still use export/import/merge to move knowledge between machines, but the git-aware features won't work.

**Q: What if I (or my agent) forget to check memory?**
A: `roco hooks install` blocks a commit that touches code linked to an unreviewed memory — but the bypass (`git commit --no-verify`) is real and always available, same as any git hook. This is enforcement-by-default with an explicit escape hatch, not an unconditional guarantee.

**Q: Stale notes are dangerous.**
A: Memories auto-flag `needs_review` when their linked code changes. You review before trusting, or mark as superseded. Nothing silently misleads.

**Q: Sharing memory across teams?**
A: Two approaches:
- **Snapshot sharing** (versioned, audited): export from one project, commit the JSONL to git, team members import.
- **Live shared database**: set `ROBO_CORTEX_GLOBAL_DB=/path/to/shared/global.db` on a *local* path all `roco` invocations can reach — not a network mount (see warning above).

**Q: Offline?**
A: Yes. Everything is local SQLite. Zero network calls unless you explicitly configure Gitea evidence verification (`ROBO_CORTEX_GITEA_URL`).

**Q: Wrong lesson?**
A: Mark as `invalidated` with a reason. Preserved in history, never suggested going forward.

**Q: Read-only database?**
A: `retrieve`/`search`/`affected` degrade gracefully on a read-only `.cortex/memory.db` (read-only checkouts, some CI setups). Reads return their result, writes (staleness refresh, usage tracking) are skipped, and `meta` includes a warning. The memory core still works, just without incidental writes that don't affect correctness.

**Q: How do I opt out of the global store?**
A: Set `ROBO_CORTEX_NO_GLOBAL=1`. CLI and MCP both skip opening `~/.cortex/global.db` entirely — `retrieve`/`search` scopes strictly to the current repo, with no cross-project knowledge channel. Useful if you want strict per-project isolation.

**Q: What's the expected scale?**
A: robo-cortex is designed and tested for thousands of memories per store (repo-scoped and global combined). Performance degrades gracefully beyond that — scoring stays O(n) per candidate, and FTS candidate set is capped at 200 for each store. If you have significantly more memories than that, consider splitting into multiple projects or archiving old memories. See ARCHITECTURE.md for details.

---

## Architecture

```
Codebase
    ↓
git pre-commit hook (roco hooks install) -- blocks commits touching unreviewed memories
    ↓
robo-cortex Memory (SQLite + FTS5)
    ↓
.cortex/memory.db (repo)  +  ~/.cortex/global.db (shared)
    ↓
retrieve_context() → ranked memories with evidence, gated by staleness + assumptions
```

No embeddings. No cloud. Just SQLite, git awareness, and an explicit enforcement layer you can inspect (`.git/hooks/pre-commit` is plain shell, readable in five seconds).

---

## Learn More

- [ARCHITECTURE.md](https://github.com/robotel-limited/robo-cortex/blob/main/ARCHITECTURE.md) — Design and data model
- [MCP_TOOLS.md](https://github.com/robotel-limited/robo-cortex/blob/main/MCP_TOOLS.md) — Tool contracts for agents
- [PYTHON_SDK.md](https://github.com/robotel-limited/robo-cortex/blob/main/PYTHON_SDK.md) — In-process Python API
- [EXPORT_IMPORT.md](https://github.com/robotel-limited/robo-cortex/blob/main/EXPORT_IMPORT.md) — Sharing knowledge across projects
- [EVALUATION.md](https://github.com/robotel-limited/robo-cortex/blob/main/EVALUATION.md) — Test results and benchmarks, including the honest token-economy numbers cited above
- [ROADMAP.md](https://github.com/robotel-limited/robo-cortex/blob/main/ROADMAP.md) — What's deliberately not built yet, and why
- [CHANGELOG.md](https://github.com/robotel-limited/robo-cortex/blob/main/CHANGELOG.md) — Release history

---

## Made By

**Free to use.** Made available by **Robotel Limited UK** ([https://robotel.top](https://robotel.top)).

The architecture was designed with Anthropic's Claude (Fable) on July 2026 as an AI development agent, applying the expertise of Robotel Limited’s developers, who bring over three years of hands-on experience building and operating AI coding agents in production.

MIT License. Open source. No telemetry. No vendor lock-in.
