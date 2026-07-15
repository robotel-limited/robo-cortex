"""Command: roco evidence (add / verify)"""

import json
import sys

from robo_cortex.core.errors import NotFoundError, RoboCortexError
from robo_cortex.core.evidence import EVIDENCE_KINDS, attach_evidence, verify_evidence
from robo_cortex.core.memory import find_memory_store
from robo_cortex.cli._common import _get_cmd_name, _store, _global_store, cli_command


@cli_command("evidence add")
def run_add(args) -> int:
    with _store(args.repo) as (repo_root, conn), _global_store() as global_conn:
        store = find_memory_store(conn, global_conn, args.id, scope=args.scope)
        result = attach_evidence(
            store,
            repo_root,
            args.id,
            kind=args.kind,
            description=args.description,
            command=args.evidence_command_text,
            expected_outcome=args.expected,
            ref=args.ref,
            cold_storage_content=args.cold_storage_content,
        )

    if args.json:
        print(json.dumps(result))
    else:
        print(
            f"Attached evidence {result['evidence_id']} "
            f"(memory evidence strength: {result['memory_evidence_strength']:.2f})"
        )
    return 0


@cli_command("evidence verify")
def run_verify(args) -> int:
    with _store(args.repo) as (repo_root, conn), _global_store() as global_conn:
        # evidence rows live in whichever store their memory lives in;
        # id sequences are independent per store. --scope disambiguates
        # an id that collides between stores, same as for memory ids.
        # repo_root is passed regardless of which store the evidence
        # lives in: it's this invocation's ambient repo context, used to
        # resolve the Gitea owner/repo via the local git remote
        # (Stage 10) for gitea_pr/gitea_issue evidence specifically.
        if args.scope == "repo":
            result = verify_evidence(conn, args.evidence_id, repo_root)
        elif args.scope == "global":
            result = verify_evidence(global_conn, args.evidence_id, repo_root)
        else:
            try:
                result = verify_evidence(conn, args.evidence_id, repo_root)
            except NotFoundError:
                result = verify_evidence(global_conn, args.evidence_id, repo_root)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    return 0


def run_no_subcommand(args) -> int:
    """Called when 'evidence' is invoked without add/verify."""
    # This will be set as the default func for the evidence parser itself
    print("error: evidence requires a subcommand (add or verify)", file=sys.stderr)
    return 1


def register(subparsers):
    p = subparsers.add_parser("evidence", help="Attach or verify evidence")
    evidence_subparsers = p.add_subparsers(dest="evidence_command")

    # add subcommand
    p_add = evidence_subparsers.add_parser("add", help="Attach evidence to a memory")
    p_add.add_argument("id", type=int)
    p_add.add_argument("--kind", choices=sorted(EVIDENCE_KINDS), required=False, default=None)
    p_add.add_argument("--description", default=None)
    # dest="evidence_command_text": argparse shares one flat Namespace across
    # nested subparsers, so a plain --command flag here would silently
    # overwrite the top-level dest="command" used for dispatch (every
    # parser's defaults get written into the same object, whether or not
    # the flag was actually passed) -- caught by a real CLI invocation
    # returning the top-level help instead of running, not by inspection.
    p_add.add_argument(
        "--command", dest="evidence_command_text", default=None
    )
    p_add.add_argument("--expected", default=None)
    p_add.add_argument("--ref", default=None)
    p_add.add_argument("--cold-storage-content", dest="cold_storage_content", default=None)
    p_add.add_argument("--repo", default=None)
    p_add.add_argument(
        "--scope", choices=["repo", "global"], default=None,
        help="Disambiguate a memory id that collides between the repo and global stores",
    )
    p_add.add_argument("--json", action="store_true")
    p_add.set_defaults(func=run_add)

    # verify subcommand
    p_verify = evidence_subparsers.add_parser("verify", help="Re-verify one evidence row")
    p_verify.add_argument("evidence_id", type=int)
    p_verify.add_argument("--repo", default=None)
    p_verify.add_argument(
        "--scope", choices=["repo", "global"], default=None,
        help="Disambiguate an evidence id that collides between the repo and global stores",
    )
    p_verify.add_argument("--json", action="store_true")
    p_verify.set_defaults(func=run_verify)

    # Default handler when no subcommand is given
    p.set_defaults(func=run_no_subcommand)
