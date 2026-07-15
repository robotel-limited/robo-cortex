"""Command: roco init"""

import json
import sys

from robo_cortex.core.init import init_repo
from robo_cortex.core.errors import RoboCortexError
from robo_cortex.core.store import open_global_store
from robo_cortex.cli._common import _get_cmd_name, cli_command


@cli_command("init")
def run(args) -> int:
    if args.use_global:
        return _run_global(args)

    result = init_repo(args.repo)

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Initialized robo-cortex in {result['db_path']}")
        if result["gitignore_updated"]:
            print(f"Added .cortex/ to {result['repo_root']}/.gitignore")
        if "warning" in result:
            print(f"warning: {result['warning']}", file=sys.stderr)
    return 0


def _run_global(args) -> int:
    """`roco init --global`: explicitly create/open the scope-B store
    (~/.cortex/global.db, ARCHITECTURE.md §2), instead of leaving it to be
    created implicitly by the first `record --scope global` call. No git
    repository is needed or resolved -- the global store lives outside any
    single repo by construction.
    """
    conn = open_global_store()
    if conn is None:
        print(
            f"{_get_cmd_name()} init --global: global store is disabled "
            "(ROBO_CORTEX_NO_GLOBAL is set)",
            file=sys.stderr,
        )
        return 1
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn.close()

    if args.json:
        print(json.dumps({"db_path": db_path}))
    else:
        print(f"Initialized robo-cortex global store in {db_path}")
        print(
            "Global memories (--scope global) require --assumptions: "
            "conditions that must match the task text verbatim before the "
            "memory is retrieved (ARCHITECTURE.md §5.4)."
        )
    return 0


def register(subparsers):
    p = subparsers.add_parser(
        "init", help="Initialize robo-cortex in a git repository"
    )
    p.add_argument(
        "--repo",
        default=None,
        help="Path inside the target repository (default: current directory)",
    )
    p.add_argument(
        "--global", dest="use_global", action="store_true",
        help="Initialize the global (scope=global) store instead (~/.cortex/global.db); no git repository needed",
    )
    p.add_argument(
        "--json", action="store_true", help="Machine-readable JSON output"
    )
    p.set_defaults(func=run)
