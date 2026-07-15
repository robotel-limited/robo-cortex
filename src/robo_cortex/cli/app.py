"""CLI main application and dispatcher."""

import argparse
import os
import sys
from pathlib import Path

from robo_cortex import __version__
from robo_cortex.cli._common import _get_cmd_name
from robo_cortex.cli.commands import ALL_COMMANDS


def build_parser(cmd_name: str) -> argparse.ArgumentParser:
    """Construct the full argument parser, every subcommand registered.

    Extracted from `main()` so anything that needs the real command
    surface -- currently `roco completion` -- introspects the same parser
    tree the CLI actually dispatches through, instead of a second,
    driftable description of it.
    """
    parser = argparse.ArgumentParser(prog=cmd_name)
    parser.add_argument(
        "--version", action="version", version=f"{cmd_name} {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    for command in ALL_COMMANDS:
        command.register(subparsers)

    return parser


def main(argv=None):
    """Main CLI entry point."""
    # Extract command name (roco or robo-cortex) from argv[0]
    if argv is None:
        argv = sys.argv[1:]
        cmd_name = Path(sys.argv[0]).name
    else:
        cmd_name = Path(argv[0]).name if argv else "robo-cortex"

    # Fallback if invoked as a Python script
    if cmd_name.endswith('.py') or '/' in cmd_name:
        cmd_name = 'robo-cortex'

    parser = build_parser(cmd_name)
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 1

    try:
        return args.func(args)
    except Exception as error:
        # Last-resort net: every expected failure mode is already a
        # RoboCortexError caught by @cli_command inside args.func, printed
        # cleanly with the right exit code. Anything that reaches here is
        # unexpected -- still no raw traceback by default (that's an
        # implementation detail leaking into a CLI's stdout/stderr contract),
        # but ROBO_CORTEX_DEBUG=1 gets the real one back for debugging.
        if os.environ.get("ROBO_CORTEX_DEBUG"):
            raise
        print(f"{cmd_name}: internal error: {error}", file=sys.stderr)
        print(
            f"{cmd_name}: this is unexpected -- set ROBO_CORTEX_DEBUG=1 for "
            "a full traceback, and please report it",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
