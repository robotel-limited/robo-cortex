"""Command: roco status"""

import json
import sys

from robo_cortex.core.lifecycle import STATUS_ACTIONS, change_status, status_batch
from robo_cortex.core.memory import find_memory_store
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, cli_command


@cli_command("status")
def run(args) -> int:
    with _store(args.repo) as (repo_root, conn), _global_store() as global_conn:
        if args.batch:
            lines = sys.stdin.read().splitlines()
            result = status_batch(conn, global_conn, repo_root, lines)
            if args.json:
                print(json.dumps(result))
            else:
                print(f"Updated {result['updated']} memories.")
                for failure in result["failed"]:
                    print(
                        f"  line {failure['line']}: {failure['error']}",
                        file=sys.stderr,
                    )
            return 0

        if not args.id or not args.action:
            print(
                "robo-cortex status: ID and ACTION are required "
                "(or use --batch to read JSON Lines from stdin)",
                file=sys.stderr,
            )
            return 2

        if not args.reason:
            print("robo-cortex status: --reason is required", file=sys.stderr)
            return 2

        new_status = STATUS_ACTIONS[args.action]
        store = find_memory_store(conn, global_conn, args.id, scope=args.scope)
        result = change_status(
            store, repo_root, args.id, new_status, args.reason,
            supersedes_link_to=args.supersedes,
        )

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Memory {result['id']} -> {result['status']}")
    return 0


def register(subparsers):
    p = subparsers.add_parser("status", help="Change a memory's status")
    p.add_argument("id", type=int, nargs="?", default=None)
    p.add_argument(
        "action",
        nargs="?",
        choices=sorted(STATUS_ACTIONS),
        default=None,
        help="Verb: activate, supersede, invalidate, abandon, or archive (state transitions—ARCHITECTURE.md §4)",
    )
    p.add_argument(
        "--reason",
        default=None,
        help="Required: explain why this status change (permanent audit trail, not just current state)",
    )
    p.add_argument("--supersedes", type=int, default=None)
    p.add_argument("--repo", default=None)
    p.add_argument(
        "--scope",
        choices=["repo", "global"],
        default=None,
        help="Disambiguate an id that collides between the repo and global stores",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        help="Read JSON Lines (id, action, reason, ...) from stdin instead of single id/action",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
