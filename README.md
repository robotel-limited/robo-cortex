# robo-cortex

[![PyPI version](https://badge.fury.io/py/robo-cortex.svg)](https://pypi.org/project/robo-cortex/)
[![Python Versions](https://img.shields.io/pypi/pyversions/robo-cortex.svg)](https://pypi.org/project/robo-cortex/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Smithery Calls](https://smithery.ai/badge/robotel-top/robo-cortex)](https://smithery.ai/servers/robotel-top/robo-cortex)

**Git-aware knowledge integrity for AI coding agents.**

Your AI agent debugs a bug, learns the lesson, and forgets it by next week — or worse, keeps citing a "lesson" that the code has since made false. robo-cortex is a local knowledge base built for that specific failure mode: memories are anchored to git blob hashes, so when the code they're about changes, the memory is automatically flagged for review instead of being silently trusted or silently lost.

---

## Why robo-cortex, not another memory tool

Most agent-memory tools are embeddings + a vector database + a cloud dependency. robo-cortex is deliberately none of that. Four things it does that a generic key-value memory store doesn't:

1. **Git-aware staleness detection.** Every memory can link to specific file paths, captured by git blob hash at record time. When the linked code changes, the memory is automatically flagged `needs_review` on the next `retrieve`/`search`/`affected` call — and a committed revert automatically heals it back. The healing requires three conditions: (a) the revert must be **committed** (git blob hash must match HEAD again), (b) the memory must have been flagged by the system (not manually via `change_status`), and (c) you must run a lazy trigger (`retrieve`/`search`/`affected`) after the revert to scan for changes. No other memory tool ties itself to your actual code's history this way.
2. **Evidence, not vibes.** Memories can carry attached evidence (test output, a commit, a re-runnable command) with a mechanically computed strength — not a judgment call. A `provisional` memory only becomes `active` once real evidence backs it, or a human explicitly promotes it.
3. **Zero dependencies, fully local.** Pure stdlib + SQLite (FTS5 for search). No embeddings, no API keys, no network calls unless you explicitly configure Gitea evidence verification. `.cortex/memory.db` is just a file — inspect it with `sqlite3` any time.
4. **A real lifecycle with an audit trail.** Every status change (`active` → `superseded` → `archived`, etc.) requires a `--reason`, permanently recorded. Nothing disappears silently; wrong lessons are marked `invalidated`, not deleted.
