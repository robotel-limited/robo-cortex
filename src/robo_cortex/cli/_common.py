"""CLI common utilities: context managers, decorators, constants."""

import sys
from contextlib import contextmanager
from pathlib import Path

from robo_cortex.core.errors import RoboCortexError
from robo_cortex.core.store import open_global_store, open_store


def _get_cmd_name():
    """Extract the command name from sys.argv[0]"""
    cmd = Path(sys.argv[0]).name
    if cmd.endswith('.py') or '/' in cmd:
        return 'robo-cortex'
    return cmd


@contextmanager
def _store(repo_arg):
    repo_root, conn = open_store(repo_arg)
    try:
        yield repo_root, conn
    finally:
        conn.close()


@contextmanager
def _global_store():
    conn = open_global_store()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _store_conn(repo_arg):
    """Same as `_store`, but yields only the connection, not (repo_root, conn).

    Exists for call sites (currently: import) that need a connection-only
    context manager to pass around -- e.g. as one of two interchangeable
    factories alongside `_global_store`. Using `_store` directly there would
    silently yield a 2-tuple where a connection is expected (that mismatch
    was exactly the `'tuple' object has no attribute 'execute'` bug in the
    original `roco import` implementation).
    """
    with _store(repo_arg) as (_repo_root, conn):
        yield conn


LINK_TYPE_ARGS = {"contradicts": "contradicts", "duplicate-of": "duplicate_of"}


def cli_command(name: str):
    """Decorator: wrap command handler to catch RoboCortexError and return exit code.

    Usage:
        @cli_command("record")
        def run(args) -> int:
            ...result = record_memory(...)...
            return 0
    """
    def wrap(fn):
        def inner(args):
            try:
                return fn(args)
            except RoboCortexError as error:
                print(f"{_get_cmd_name()} {name}: {error}", file=sys.stderr)
                return error.exit_code
        return inner
    return wrap
