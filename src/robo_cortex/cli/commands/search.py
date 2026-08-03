"""Command: roco search"""

import json
import sys

from robo_cortex.core.retrieve import DEFAULT_SEARCH_LIMIT, search_memory
from robo_cortex.cli._common import _get_cmd_name, _store_or_none, _global_store, cli_command


@cli_command("search")
def run(args) -> int:
    if not args.query:
        print("robo-cortex search: --query is required", file=sys.stderr)
        return 2

    with _store_or_none(args.repo) as (repo_root, conn), _global_store() as global_conn:
        if conn is None and args.scope == "repo":
            print(
                "robo-cortex search: no repo store available (not inside a git "
                "repo, or 'robo-cortex init' never ran there) -- pass --repo, "
                "or drop --scope repo to also search the global store",
                file=sys.stderr,
            )
            return 2
        result = search_memory(
            conn,
            repo_root,
            query=args.query,
            scope=args.scope,
            type=args.type,
            status=args.status,
            limit=args.limit,
            global_conn=global_conn,
        )

    if args.json:
        print(json.dumps(result))
    else:
        print(f"matched={result['matched']} returned={result['returned']}")
        for item in result["data"]:
            print(f"[{item['id']}] {item['type']:12s} {item['status']:13s} {item['statement']}")
    return 0


def register(subparsers):
    p = subparsers.add_parser(
        "search", help="Search memories by area, task, or concept (exploration, not budgeted)"
    )
    p.add_argument("--repo", default=None)
    p.add_argument("--query", default=None)
    p.add_argument("--scope", default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--status", default=None)
    p.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
