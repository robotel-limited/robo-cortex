"""Command: roco show"""

import json
import sys

from robo_cortex.core.memory import find_memory_store, get_memory
from robo_cortex.core.retrieve import explain_memory_score
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, cli_command
from robo_cortex.cli._output import _format_score_breakdown, format_status


@cli_command("show")
def run(args) -> int:
    with _store(args.repo) as (_repo_root, conn), _global_store() as global_conn:
        store = find_memory_store(conn, global_conn, args.id, scope=args.scope)
        result = get_memory(store, args.id)
        if args.explain_against:
            result["score_breakdown"] = explain_memory_score(
                conn, args.id, args.explain_against,
                global_conn=global_conn, scope=args.scope,
            )

    if args.json:
        print(json.dumps(result))
    else:
        print(
            f"[{result['id']}] {result['type']} "
            f"({result['scope']}, {format_status(result['status'])}, "
            f"confidence={result['confidence']})"
        )
        print(result["statement"])
        if result["status_reason"]:
            print(f"status reason: {result['status_reason']}")
        if result["why_it_matters"]:
            print(f"why it matters: {result['why_it_matters']}")
        if result["assumptions"]:
            print(f"assumptions: {result['assumptions']}")
        for path in result["paths"]:
            print(f"  path: {path['path']}  blob_hash: {path['blob_hash']}")
        for item in result["evidence"]:
            print(f"  evidence [{item['id']}] {item['kind']} ({item['status']}): {item['description']}")
        for link in result["links"]:
            print(f"  link: {link['direction']} {link['link_type']} <-> memory {link['memory_id']}")
        if "score_breakdown" in result:
            print(f"  explain: {_format_score_breakdown(result['score_breakdown'])}")
    return 0


def register(subparsers):
    p = subparsers.add_parser("show", help="Show one memory in full")
    p.add_argument("id", type=int)
    p.add_argument("--repo", default=None)
    p.add_argument(
        "--scope", choices=["repo", "global"], default=None,
        help="Disambiguate an id that collides between the repo and global stores",
    )
    p.add_argument(
        "--explain-against", dest="explain_against", default=None,
        help="Print this memory's score components against a hypothetical task",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
