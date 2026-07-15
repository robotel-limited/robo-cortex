"""Command: roco list"""

import json
import sys

from robo_cortex.core.memory import list_memories
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, cli_command
from robo_cortex.cli._output import format_status


@cli_command("list")
def run(args) -> int:
    with _store(args.repo) as (_repo_root, conn), _global_store() as global_conn:
        results = []
        if args.scope in (None, "repo"):
            results += list_memories(
                conn,
                status=args.status,
                scope=args.scope,
                type=args.type,
                needs_consolidation=args.needs_consolidation,
                abandoned_without_lesson=args.abandoned_without_lesson,
            )
        if args.scope in (None, "global"):
            results += list_memories(
                global_conn,
                status=args.status,
                scope=args.scope,
                type=args.type,
                needs_consolidation=args.needs_consolidation,
                abandoned_without_lesson=args.abandoned_without_lesson,
            )
        results.sort(key=lambda m: m["id"])

    if args.json:
        print(json.dumps(results))
    else:
        if not results:
            print("No memories found.")
        for memory in results:
            print(
                f"[{memory['id']}] {memory['type']:12s} {memory['scope']:6s} "
                f"{format_status(memory['status'], width=13)} {memory['statement']}"
            )
    return 0


def register(subparsers):
    p = subparsers.add_parser("list", help="List memories")
    p.add_argument("--repo", default=None)
    p.add_argument("--status", default=None)
    p.add_argument("--scope", choices=["repo", "global"], default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--needs-consolidation", action="store_true")
    p.add_argument("--abandoned-without-lesson", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
