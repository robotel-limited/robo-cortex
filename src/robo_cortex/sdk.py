"""Python SDK for robo-cortex: direct, in-process access to the memory core.

Unlike the pre-0.3.0 SDK (a subprocess wrapper that shelled out to the CLI
and swallowed every exception into an {"error": ...} dict), every method
here calls straight into `robo_cortex.core` -- no subprocess, no JSON
round-trip through stdout. This is the same pattern `mcp_server.py` already
uses (call core functions directly); the SDK differs only in opening
connections per call instead of once at server startup.

RoboCortexError subclasses (NotInitializedError, ValidationError, ...)
propagate to the caller instead of being caught here -- catch what you
need, or let a bug surface loudly instead of silently returning a dict
with an "error" key nothing was checking for.

Connections are opened and closed within each method call, not held across
the RoboCortex instance's lifetime: the CLI itself never holds a connection
open across two commands (`roco record` and `roco retrieve` are separate
processes), and an agent process that calls `record()` now and `retrieve()`
minutes later shouldn't be holding a stale SQLite connection or an
unreleased lock for the time in between. The cost is one open+migrate per
call (a few milliseconds against a local file) -- a small, predictable
price for never worrying about connection lifetime in a long-running
agent process.
"""

from pathlib import Path
from typing import Optional

from robo_cortex.core.memory import find_memory_store as _find_memory_store
from robo_cortex.core.memory import get_memory as _get_memory
from robo_cortex.core.memory import list_memories as _list_memories
from robo_cortex.core.memory import record_memory as _record_memory
from robo_cortex.core.retrieve import DEFAULT_BUDGET_ITEMS, DEFAULT_BUDGET_TOKENS, DEFAULT_SEARCH_LIMIT
from robo_cortex.core.retrieve import retrieve_context as _retrieve_context
from robo_cortex.core.retrieve import search_memory as _search_memory
from robo_cortex.core.store import open_global_store, open_store


class RoboCortex:
    """In-process access to one repository's memory store (+ the shared
    global store). No subprocess involved -- see module docstring.
    """

    def __init__(self, repo_path: Optional[str] = None):
        self.repo_path = str(Path(repo_path).resolve()) if repo_path else str(Path.cwd())

    def retrieve(
        self,
        task: str,
        paths: Optional[list] = None,
        budget_items: int = DEFAULT_BUDGET_ITEMS,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        explain: bool = False,
    ) -> dict:
        """Ranked, budgeted context pack for a task (same result shape as
        `roco retrieve --json`)."""
        repo_root, conn = open_store(self.repo_path)
        try:
            global_conn = open_global_store()
            try:
                return _retrieve_context(
                    conn, repo_root, task=task, paths=paths,
                    budget_items=budget_items, budget_tokens=budget_tokens,
                    explain=explain, global_conn=global_conn,
                )
            finally:
                global_conn.close()
        finally:
            conn.close()

    def record(
        self,
        type: str,
        statement: str,
        scope: str = "repo",
        confidence: str = "medium",
        why_it_matters: Optional[str] = None,
        assumptions: Optional[str] = None,
        paths: Optional[list] = None,
        lesson_from: Optional[int] = None,
    ) -> dict:
        """Create a memory. scope='global' requires non-empty `assumptions`
        (ARCHITECTURE.md §5.4: the preconditions under which the lesson
        applies) and is written to the shared cross-project store
        (~/.cortex/global.db), not this repo's local one -- this is the bug
        that made scope='global' unreachable through the pre-0.3.0 SDK.
        """
        repo_root, repo_conn = open_store(self.repo_path)
        try:
            if scope == "global":
                global_conn = open_global_store()
                try:
                    return _record_memory(
                        global_conn, repo_root, type=type, scope=scope,
                        statement=statement, confidence=confidence,
                        why_it_matters=why_it_matters, assumptions=assumptions,
                        paths=paths, lesson_from=lesson_from,
                    )
                finally:
                    global_conn.close()
            return _record_memory(
                repo_conn, repo_root, type=type, scope=scope,
                statement=statement, confidence=confidence,
                why_it_matters=why_it_matters, assumptions=assumptions,
                paths=paths, lesson_from=lesson_from,
            )
        finally:
            repo_conn.close()

    def search(
        self,
        query: str,
        scope: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> dict:
        """Exploration search -- broader and less strictly budgeted than
        `retrieve()`; unlike retrieve, global-store results are not gated
        by assumptions (this is an explicit lookup, not a proactive
        suggestion)."""
        repo_root, conn = open_store(self.repo_path)
        try:
            global_conn = open_global_store()
            try:
                return _search_memory(
                    conn, repo_root, query=query, scope=scope, type=type,
                    status=status, limit=limit, global_conn=global_conn,
                )
            finally:
                global_conn.close()
        finally:
            conn.close()

    def list_memories(
        self,
        status: Optional[str] = None,
        scope: Optional[str] = None,
        type: Optional[str] = None,
    ) -> list:
        """List memories, merged and id-sorted. scope=None (default)
        returns both repo and global stores, same as `roco list`."""
        repo_root, conn = open_store(self.repo_path)
        try:
            results = []
            if scope in (None, "repo"):
                results += _list_memories(conn, status=status, scope=scope, type=type)
            if scope in (None, "global"):
                global_conn = open_global_store()
                try:
                    results += _list_memories(global_conn, status=status, scope=scope, type=type)
                finally:
                    global_conn.close()
            results.sort(key=lambda m: m["id"])
            return results
        finally:
            conn.close()

    def get_memory(self, id: int, scope: Optional[str] = None) -> dict:
        """Full detail on one memory: fields, paths, evidence, links.
        `scope` disambiguates an id that collides between the repo and
        global stores (their id sequences are independent counters)."""
        repo_root, conn = open_store(self.repo_path)
        try:
            global_conn = open_global_store()
            try:
                store = _find_memory_store(conn, global_conn, id, scope=scope)
                return _get_memory(store, id)
            finally:
                global_conn.close()
        finally:
            conn.close()


# Convenience functions for one-off calls without instantiating RoboCortex,
# mirroring the CLI's flat commands. Each just delegates to a fresh instance.

def retrieve(task: str, repo_path: Optional[str] = None, **kwargs) -> dict:
    """Retrieve memories for a task. See RoboCortex.retrieve for kwargs."""
    return RoboCortex(repo_path).retrieve(task, **kwargs)


def record(
    type: str,
    statement: str,
    repo_path: Optional[str] = None,
    **kwargs,
) -> dict:
    """Record a new memory. See RoboCortex.record for kwargs (scope,
    confidence, why_it_matters, assumptions, paths, lesson_from)."""
    return RoboCortex(repo_path).record(type, statement, **kwargs)


def search(query: str, repo_path: Optional[str] = None, **kwargs) -> dict:
    """Search memories. See RoboCortex.search for kwargs."""
    return RoboCortex(repo_path).search(query, **kwargs)
