"""Command: roco link"""

import json
import sys

from robo_cortex.core.lifecycle import create_link
from robo_cortex.core.memory import find_memory_store
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, LINK_TYPE_ARGS, cli_command


@cli_command("link")
def run(args) -> int:
    link_type = LINK_TYPE_ARGS[args.link_type]
    with _store(args.repo) as (_repo_root, conn), _global_store() as global_conn:
        store1 = find_memory_store(conn, global_conn, args.id1, scope=args.scope)
        store2 = find_memory_store(conn, global_conn, args.id2, scope=args.scope)
        if store1 is not store2:
            print(
                "robo-cortex link: cannot link memories across the repo "
                "and global stores (memory_link is a same-store reference)",
                file=sys.stderr,
            )
            return 1
        result = create_link(store1, args.id1, args.id2, link_type)

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Linked {result['from_id']} --{result['link_type']}--> {result['to_id']}")
    return 0


def register(subparsers):
    p = subparsers.add_parser("link", help="Link two memories as contradicting or duplicate")
    p.add_argument("id1", type=int)
    p.add_argument("link_type", choices=sorted(LINK_TYPE_ARGS))
    p.add_argument("id2", type=int)
    p.add_argument("--repo", default=None)
    p.add_argument(
        "--scope",
        choices=["repo", "global"],
        default=None,
        help="Disambiguate ids that collide between the repo and global stores "
             "(both id1 and id2 must be in the same store to link)",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
