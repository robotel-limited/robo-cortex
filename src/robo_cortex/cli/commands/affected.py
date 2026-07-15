"""Command: roco affected"""

import json
import sys

from robo_cortex.core.invalidate import affected
from robo_cortex.cli._common import _get_cmd_name, _store, cli_command


@cli_command("affected")
def run(args) -> int:
    with _store(args.repo) as (repo_root, conn):
        result = affected(
            conn,
            repo_root,
            diff_range=args.diff_range,
            staged=args.staged,
            working=args.working,
        )

    if args.json:
        print(json.dumps(result))
    else:
        if not result["data"]:
            print("No memories affected.")
        for item in result["data"]:
            print(f"[{item['id']}] {item['reason']}  {item['statement']}")
    return 0


def register(subparsers):
    p = subparsers.add_parser(
        "affected", help="List memories put at risk by recent changes or a diff"
    )
    p.add_argument("--repo", default=None)
    p.add_argument("--diff-range", default=None)
    p.add_argument("--staged", action="store_true")
    p.add_argument("--working", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
