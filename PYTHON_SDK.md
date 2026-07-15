# Python SDK for robo-cortex

Direct, in-process access to robo-cortex from Python code — no subprocess, no CLI parsing. Every call goes straight into `robo_cortex.core`, the same functions the CLI and MCP server use.

## Installation

The SDK is part of the main package, no extras needed:

```bash
pip install robo-cortex
```

## Quick Start

```python
from robo_cortex import retrieve, record

# Before implementing a feature, check if we've learned a solution
memories = retrieve("clipboard copy to browser", repo_path="/srv/project")
if memories["data"]:
    solution = memories["data"][0]["statement"]
    print(f"Use this approach: {solution}")
else:
    print("New problem, will implement and save lessons")

# After solving, save for next time
record(
    type="lesson",
    statement="Copy-to-clipboard on HTTP: Use textarea + execCommand fallback",
    confidence="high",
    repo_path="/srv/project",
)
```

## Errors propagate — they are not swallowed

Every SDK call raises a real exception on failure instead of returning a dict with an `"error"` key. Catch what you expect, let the rest surface:

```python
from robo_cortex import retrieve
from robo_cortex.core.errors import NotInitializedError

try:
    result = retrieve("some task", repo_path="/srv/project")
except NotInitializedError:
    # /srv/project is a real git repository, but 'roco init' hasn't run there yet
    print("Run 'robo-cortex init' in that repo first")
```

Exception classes (all subclasses of `robo_cortex.core.errors.RoboCortexError`): `NotInitializedError`, `NotAGitRepoError`, `ValidationError` (invalid type/scope/confidence, dead path, missing `assumptions` on a global-scope memory), `NotFoundError` (unknown memory id), `IllegalTransitionError` (invalid status change), `AlreadyInitializedError`, `BusyError`.

## API Reference

### Convenience Functions

**`retrieve(task, repo_path=None, paths=None, budget_items=15, budget_tokens=..., explain=False)`**
- Ranked, budgeted context pack for a task — the same result shape as `roco retrieve --json`.
- Returns a dict: `{"meta": {...}, "data": [...]}`. `meta["matched"]` is how many memories passed candidacy; `data` is the ranked, budget-truncated pack.
- Example:
  ```python
  result = retrieve("async/await deadlock", repo_path="/srv/project")
  for memory in result["data"]:
      print(f"ID {memory['id']}: {memory['statement']}")
  ```

**`record(type, statement, repo_path=None, scope="repo", confidence="medium", why_it_matters=None, assumptions=None, paths=None, lesson_from=None)`**
- Save a new memory. Returns `{"id": ..., "status": "provisional", "paths": [...]}`.
- `type`: one of `fact`, `decision`, `convention`, `hypothesis`, `experiment`, `lesson`, `open_question`.
- `scope="global"` requires non-empty `assumptions` — the preconditions under which the lesson applies (ARCHITECTURE.md §5.4). Without it, `record()` raises `ValidationError` rather than silently degrading the memory into a universal rule.
- Example:
  ```python
  result = record(
      type="lesson",
      statement="Safari 14 breaks CSS grid+gap. Use flexbox+margin instead.",
      scope="global",
      confidence="high",
      assumptions="web app targeting Safari 14, uses CSS grid with the gap property",
      repo_path="/srv/project",
  )
  print(f"Recorded memory ID {result['id']}")
  ```

**`search(query, repo_path=None, scope=None, type=None, status=None, limit=15)`**
- Full-text search — broader and less strictly budgeted than `retrieve()`. Unlike `retrieve`, global-store results are not gated by `assumptions` (this is an explicit lookup, not a proactive suggestion).
- Returns `{"matched": ..., "returned": ..., "data": [...]}`.

### RoboCortex Class

For multiple operations against the same repo, avoid re-resolving `repo_path` each call:

```python
from robo_cortex import RoboCortex

cortex = RoboCortex("/srv/my-agent-project")

# Retrieve memories
memories = cortex.retrieve("async patterns")

# Record memory
result = cortex.record(
    type="decision",
    statement="Chose Promise.all() over Promise.race() for parallel operations",
)

# Search
results = cortex.search("database migration")

# List all memories (repo + global, merged and id-sorted)
all_memories = cortex.list_memories()

# Get specific memory
memory = cortex.get_memory(id=1)
```

**Methods:**
- `retrieve(task, paths=None, budget_items=15, budget_tokens=..., explain=False)` → dict
- `record(type, statement, scope="repo", confidence="medium", why_it_matters=None, assumptions=None, paths=None, lesson_from=None)` → dict
- `search(query, scope=None, type=None, status=None, limit=15)` → dict
- `list_memories(status=None, scope=None, type=None)` → list[dict]
- `get_memory(id, scope=None)` → dict — `scope` disambiguates an id that collides between the repo and global stores (their id sequences are independent counters)

Connections are opened and closed within each method call, not held across the `RoboCortex` instance's lifetime — safe to keep one `RoboCortex` object around in a long-running agent process and call methods on it minutes or hours apart.

## Use Cases

### 1. Coding Agent — Check Before Coding

```python
from robo_cortex import retrieve, record

def implement_feature(feature_name, repo_path):
    # Step 1: Check if solved before
    memories = retrieve(feature_name, repo_path=repo_path)
    if memories["data"]:
        print("Solution from prior project:")
        print(memories["data"][0]["statement"])
        return memories["data"][0]["statement"]

    # Step 2: Implement from scratch
    solution = my_implementation(feature_name)

    # Step 3: Save for next time
    record(
        type="lesson",
        statement=f"{feature_name}: {solution}",
        confidence="high",
        repo_path=repo_path,
    )
    return solution
```

### 2. Debugging — Log Lessons

```python
from robo_cortex import record

try:
    risky_operation()
except SpecificError:
    # Save the fix for next time
    record(
        type="lesson",
        statement="SpecificError: Occurs when X. Fix: Use Y instead.",
        confidence="high",
        repo_path="/srv/project",
    )
    raise
```

### 3. Architecture Decisions — Record Context

```python
from robo_cortex import record

# After deciding on tech stack
record(
    type="decision",
    statement="Chose SQLite over PostgreSQL for this project due to deployment simplicity",
    scope="repo",
    confidence="high",
    why_it_matters="Single-file database reduces ops overhead",
    repo_path="/srv/project",
)
```

### 4. Multi-Step Workflow

```python
from robo_cortex import RoboCortex

cortex = RoboCortex("/srv/project")

# Check all prior learnings
all_memories = cortex.list_memories()
lessons = [m for m in all_memories if m["type"] == "lesson"]

print(f"This project has learned {len(lessons)} lessons:")
for lesson in lessons:
    print(f"  - {lesson['statement'][:60]}...")

# Add to our knowledge
cortex.record(
    type="fact",
    statement="Database backup runs at 2 AM UTC, don't lock tables then",
    confidence="high",
)
```

## Scope: Global vs Repo

**Use `scope="repo"`** (default) for project-specific learnings:
- This codebase's patterns (we use FastAPI + SQLAlchemy)
- Project-specific bugs (this version of Node.js breaks X)
- Infrastructure decisions (our deployment uses Docker)

**Use `scope="global"`** for reusable knowledge:
- Language/framework patterns (async/await deadlock in Python)
- Library bugs (Safari 14 CSS grid bug)
- Best practices (SQL injection prevention)

`scope="global"` requires `assumptions` — the preconditions under which the lesson applies:

```python
record(
    type="lesson",
    statement="Copy-to-clipboard fails on HTTP. Use textarea + execCommand fallback.",
    scope="global",
    assumptions="web app with a copy-to-clipboard feature, needs to work on HTTP",
    confidence="high",
)
```

## Performance

- Local SQLite database (`.cortex/memory.db` + `~/.cortex/global.db`) — no network calls, no subprocess.
- Each call opens and closes its own connection (a few milliseconds against a local file); batch reads in Python rather than looping many single-id calls:

```python
# Good: one query, filter in Python
cortex = RoboCortex("/srv/project")
all_memories = cortex.list_memories()
lessons = [m for m in all_memories if m["type"] == "lesson"]

# Avoid: N separate connections for N ids you already know about
for memory_id in known_ids:
    cortex.get_memory(memory_id)
```

## CLI vs SDK vs MCP

| Task | CLI | SDK | MCP |
|------|-----|-----|-----|
| One-off shell command | ✅ `roco retrieve --task "..."` | ❌ overkill | ❌ n/a |
| Python script or agent code | ❌ subprocess call | ✅ `retrieve(...)` | ❌ n/a |
| LLM agent with tool-calling | ❌ n/a | ❌ n/a | ✅ agent decides when to call |
| Error handling | parse stderr + exit code | ✅ native exceptions | ✅ SDK-caught, returned as tool error |

See [MCP_TOOLS.md](MCP_TOOLS.md) for the MCP tool surface, [ARCHITECTURE.md](ARCHITECTURE.md) for internals.

## Troubleshooting

**`NotInitializedError`**
- The target repo hasn't been initialized: run `roco init` there first, or call `robo_cortex.core.init.init_repo(repo_path)` from Python.

**`NotAGitRepoError`**
- `repo_path` isn't inside a git repository. robo-cortex's staleness detection is git-anchored — see the FAQ in [README.md](README.md).

**Empty `retrieve()`/`search()` results**
- No memories recorded yet, or `repo_path` points at a different repository than the one memories were saved in.
- For `retrieve()` specifically: global-scope memories must pass the assumptions gate (ARCHITECTURE.md §5.4) — use `search()` to see candidates that didn't clear it.

**`ValidationError: scope='global' memories require non-empty assumptions`**
- Pass `assumptions="..."` describing when the lesson applies, or use `scope="repo"` if it's project-specific.
