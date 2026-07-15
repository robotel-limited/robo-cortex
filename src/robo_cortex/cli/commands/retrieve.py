"""Command: roco retrieve"""

import json
import sys

from robo_cortex.core.retrieve import (
    DEFAULT_BUDGET_ITEMS,
    DEFAULT_BUDGET_TOKENS,
    retrieve_context,
)
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, cli_command
from robo_cortex.cli._output import _format_score_breakdown, format_status


@cli_command("retrieve")
def run(args) -> int:
    if not args.task:
        print("robo-cortex retrieve: --task is required", file=sys.stderr)
        return 2

    with _store(args.repo) as (repo_root, conn), _global_store() as global_conn:
        result = retrieve_context(
            conn,
            repo_root,
            task=args.task,
            paths=args.paths,
            budget_items=args.budget_items,
            budget_tokens=args.budget_tokens,
            explain=args.explain,
            global_conn=global_conn,
        )

    if args.json:
        print(json.dumps(result))
    else:
        meta = result["meta"]
        print(
            f"matched={meta['matched']} returned={meta['returned']} "
            f"needs_review={meta['needs_review']} contradicted={meta['contradicted']}"
        )
        if meta["matched"] == 0:
            print(
                "  hint: no memory passed candidacy (global-scope items must pass"
            )
            print(
                "        the assumptions gate — see ARCHITECTURE.md §5.4). Try:"
            )
            print(f"        roco search --query \"{args.task}\"")
            print(
                "        roco show <id> --explain-against \"<task>\" (see why candidates didn't match)"
            )
        for omission in meta["omitted"]:
            print(f"  omitted: {omission['count']} ({omission['reason']})")
        if args.explain and "omitted_details" in meta:
            for detail in meta["omitted_details"]:
                print(f"    - id={detail['id']} scope={detail['scope']} omitted due to {detail['reason']}")
        for item in result["data"]:
            # Status is only surfaced when it's not the common case (active):
            # a needs_review item buried in a ranked result list is worth
            # flagging inline, not just visible via the aggregate count above.
            status_marker = (
                f"{format_status(item['status'])} " if item["status"] != "active" else ""
            )
            print(
                f"[{item['id']}] score={item['score']:.3f} "
                f"{item['scope']:6s} {item['type']:12s} {status_marker}{item['statement']}"
            )
            if args.explain:
                print(f"    {_format_score_breakdown(item['score_breakdown'])}")
    return 0


def register(subparsers):
    p = subparsers.add_parser(
        "retrieve", help="Retrieve a ranked, budgeted context pack for a task"
    )
    p.add_argument("--repo", default=None)
    p.add_argument("--task", default=None)
    p.add_argument("--path", dest="paths", action="append", default=[])
    p.add_argument(
        "--budget-items", type=int, default=DEFAULT_BUDGET_ITEMS
    )
    p.add_argument(
        "--budget-tokens", type=int, default=DEFAULT_BUDGET_TOKENS
    )
    p.add_argument("--explain", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
