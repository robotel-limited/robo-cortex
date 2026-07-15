"""Command: roco record"""

import json
import sys

from robo_cortex.core.memory import (
    CONFIDENCES,
    SCOPES,
    TYPES,
    record_batch,
    record_memory,
)
from robo_cortex.core.invalidate import add_path, update_path
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, cli_command


@cli_command("record")
def run(args) -> int:
    with _store(args.repo) as (repo_root, conn):
        if args.update_path:
            if not (args.id and args.old_path and args.new_path):
                print(
                    "robo-cortex record --update-path: ID, --old-path, "
                    "and --new-path are all required",
                    file=sys.stderr,
                )
                return 2
            result = update_path(conn, repo_root, args.id, args.old_path, args.new_path)
            if args.json:
                print(json.dumps(result))
            else:
                print(f"Updated memory {result['id']}: {args.old_path} -> {args.new_path}")
            return 0

        if args.add_path:
            if not args.id:
                print(
                    "robo-cortex record --add-path: ID is required",
                    file=sys.stderr,
                )
                return 2
            result = add_path(conn, repo_root, args.id, args.add_path)
            if args.json:
                print(json.dumps(result))
            else:
                print(f"Added path to memory {result['id']}: {args.add_path}")
            return 0

        if args.batch:
            lines = sys.stdin.read().splitlines()
            result = record_batch(conn, repo_root, lines)
            if args.json:
                print(json.dumps(result))
            else:
                print(f"Created {result['created']} memories.")
                for failure in result["failed"]:
                    print(
                        f"  line {failure['line']}: {failure['error']}",
                        file=sys.stderr,
                    )
            return 0

        if not (args.type and args.scope and args.statement and args.confidence):
            print(
                "robo-cortex record: --type, --scope, --statement, and "
                "--confidence are required (or use --batch to read JSON "
                "Lines from stdin, --update-path to relink an existing "
                "memory, or --add-path to attach a path to one)",
                file=sys.stderr,
            )
            return 2

        if args.scope == "global":
            # scope='global' memories live in ~/.cortex/global.db, not
            # the local repo store -- ARCHITECTURE.md §2: scope B "cannot
            # live in one repository's .cortex/".
            with _global_store() as global_conn:
                result = record_memory(
                    global_conn,
                    repo_root,
                    type=args.type,
                    scope=args.scope,
                    statement=args.statement,
                    confidence=args.confidence,
                    why_it_matters=args.why_it_matters,
                    assumptions=args.assumptions,
                    paths=args.paths,
                    lesson_from=args.lesson_from,
                )
        else:
            result = record_memory(
                conn,
                repo_root,
                type=args.type,
                scope=args.scope,
                statement=args.statement,
                confidence=args.confidence,
                why_it_matters=args.why_it_matters,
                assumptions=args.assumptions,
                paths=args.paths,
                lesson_from=args.lesson_from,
            )

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Recorded memory {result['id']} (status: {result['status']})")
        for path in result["paths"]:
            print(f"  path: {path['path']}  blob_hash: {path['blob_hash']}")
    return 0


def register(subparsers):
    p = subparsers.add_parser(
        "record",
        help="Record a new memory",
        description="Record a new memory in this repository or globally.\n"
        "New memories start in 'provisional' status. Use 'roco status <id> activate' to promote to 'active', "
        "or attach evidence which auto-promotes provisional→active on the first evidence.",
    )
    p.add_argument("id", nargs="?", type=int, default=None, help="Used with --update-path or --add-path")
    p.add_argument("--repo", default=None)
    p.add_argument("--type", choices=sorted(TYPES), default=None, help="Memory type: decision, lesson, fact, etc.")
    p.add_argument("--scope", choices=sorted(SCOPES), default=None, help="Memory scope: 'repo' (this project) or 'global' (reusable)")
    p.add_argument("--statement", default=None)
    p.add_argument(
        "--confidence", choices=sorted(CONFIDENCES), default=None,
        help="Confidence level: low, medium, or high"
    )
    p.add_argument("--why", dest="why_it_matters", default=None)
    p.add_argument("--assumptions", default=None, help="Comma-separated preconditions (for global memories, all must match the task text verbatim)")
    p.add_argument(
        "--path", dest="paths", action="append", default=[]
    )
    p.add_argument(
        "--lesson-from", dest="lesson_from", type=int, default=None,
        help="Link a new type=lesson memory back to the abandoned memory it compresses",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        help="Read JSON Lines from stdin instead of the flags above",
    )
    p.add_argument(
        "--update-path", action="store_true",
        help="Relink an existing memory's path (needs ID, --old-path, --new-path)",
    )
    p.add_argument("--old-path", default=None)
    p.add_argument("--new-path", default=None)
    p.add_argument(
        "--add-path", dest="add_path", default=None,
        help="Attach a new path to an existing memory (needs ID and --add-path); "
        "useful for a file that didn't exist at HEAD when the memory was first recorded",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
