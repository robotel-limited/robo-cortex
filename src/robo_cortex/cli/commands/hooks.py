"""Command: roco hooks (install / uninstall / status / check)"""

import json
import sys

from robo_cortex.core.hooks import HOOK_FILENAME, POST_COMMIT_HOOK_FILENAME
from robo_cortex.core.hooks import install as core_install
from robo_cortex.core.hooks import status as core_status
from robo_cortex.core.hooks import uninstall as core_uninstall
from robo_cortex.core.invalidate import affected as core_affected
from robo_cortex.cli._common import _get_cmd_name, _store, cli_command


def _hook_name(args) -> str:
    return POST_COMMIT_HOOK_FILENAME if args.post_commit else HOOK_FILENAME


@cli_command("hooks install")
def run_install(args) -> int:
    hook_name = _hook_name(args)
    with _store(args.repo) as (repo_root, _conn):
        result = core_install(repo_root, force=args.force, hook_name=hook_name)

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Installed {hook_name} hook at {result['path']}")
        if result["chained"]:
            print(f"Chained after your existing {hook_name} hook (it still runs first).")
        if hook_name == POST_COMMIT_HOOK_FILENAME:
            print("Informational only -- reports affected memories after each commit, never blocks.")
        else:
            print("Bypass any time with: git commit --no-verify")
    return 0


@cli_command("hooks uninstall")
def run_uninstall(args) -> int:
    hook_name = _hook_name(args)
    with _store(args.repo) as (repo_root, _conn):
        result = core_uninstall(repo_root, hook_name=hook_name)

    if args.json:
        print(json.dumps(result))
    else:
        if not result["uninstalled"]:
            print(f"Nothing to remove: {result['reason']}")
        elif result["deleted"]:
            print(f"Removed {hook_name} hook at {result['path']}")
        else:
            print(f"Removed robo-cortex's block from {result['path']} (your own hook content remains)")
    return 0


@cli_command("hooks status")
def run_status(args) -> int:
    hook_name = _hook_name(args)
    with _store(args.repo) as (repo_root, _conn):
        result = core_status(repo_root, hook_name=hook_name)

    if args.json:
        print(json.dumps(result))
    else:
        if not result["installed"]:
            reason = result.get("note", "not installed")
            print(f"{hook_name} hook: {reason}")
        else:
            chained = " (chained after another hook)" if result["chained"] else ""
            print(f"{hook_name} hook: installed at {result['path']}{chained}")
    return 0


@cli_command("hooks check")
def run_check(args) -> int:
    """Run by the installed pre-commit hook itself -- not usually invoked
    by hand. Checks staged changes against `affected`; exits nonzero (and
    prints a review block to stderr) only if something needs review.
    """
    with _store(args.repo) as (repo_root, conn):
        result = core_affected(conn, repo_root, staged=True)

    if not result["data"]:
        return 0

    print(
        "robo-cortex: this commit touches code linked to memories that need review:",
        file=sys.stderr,
    )
    for item in result["data"]:
        print(f"  [{item['id']}] {item['reason']}  {item['statement']}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Review with: roco show <id>", file=sys.stderr)
    print(
        "Then either re-verify (roco status <id> activate --reason \"...\") "
        "or supersede it, and commit again.",
        file=sys.stderr,
    )
    print("To bypass this check: git commit --no-verify", file=sys.stderr)
    return 1


def register(subparsers):
    p = subparsers.add_parser("hooks", help="Manage robo-cortex's git hooks (pre-commit, post-commit)")
    hooks_subparsers = p.add_subparsers(dest="hooks_command")

    p_install = hooks_subparsers.add_parser(
        "install", help="Install the pre-commit hook (blocks commits touching unreviewed memories)"
    )
    p_install.add_argument("--repo", default=None)
    p_install.add_argument(
        "--force", action="store_true",
        help="Chain after an existing non-robo-cortex hook instead of refusing to install",
    )
    p_install.add_argument(
        "--post-commit", action="store_true",
        help="Install the post-commit hook instead (informational report after each commit, never blocks)",
    )
    p_install.add_argument("--json", action="store_true")
    p_install.set_defaults(func=run_install)

    p_uninstall = hooks_subparsers.add_parser("uninstall", help="Remove robo-cortex's pre-commit hook")
    p_uninstall.add_argument("--repo", default=None)
    p_uninstall.add_argument(
        "--post-commit", action="store_true",
        help="Remove the post-commit hook instead",
    )
    p_uninstall.add_argument("--json", action="store_true")
    p_uninstall.set_defaults(func=run_uninstall)

    p_status = hooks_subparsers.add_parser("status", help="Show whether the pre-commit hook is installed")
    p_status.add_argument("--repo", default=None)
    p_status.add_argument(
        "--post-commit", action="store_true",
        help="Report on the post-commit hook instead",
    )
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=run_status)

    p_check = hooks_subparsers.add_parser(
        "check", help="Check staged changes against affected memories (used by the installed hook itself)"
    )
    p_check.add_argument("--repo", default=None)
    p_check.set_defaults(func=run_check)

    def _no_subcommand(args) -> int:
        print("error: hooks requires a subcommand (install, uninstall, status, or check)", file=sys.stderr)
        return 1

    p.set_defaults(func=_no_subcommand)
