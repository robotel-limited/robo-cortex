"""Command: roco mcp"""

import sys

from robo_cortex.core.errors import RoboCortexError
from robo_cortex.cli._common import _get_cmd_name, cli_command


@cli_command("mcp")
def run(args) -> int:
    # Lazy import: the mcp SDK is only needed for this one subcommand, not
    # for every CLI invocation -- keeps `robo-cortex record`/`show`/etc.
    # fast and independent of an mcp package version, matching the mission's
    # "every third-party dependency must be justified" posture (justified
    # exactly here, nowhere else).
    try:
        from robo_cortex.mcp_server import run as run_mcp_server
    except ImportError:
        print(
            f"{_get_cmd_name()} mcp: the 'mcp' package is not installed. "
            f"Install it with: pip install 'robo-cortex[mcp]'",
            file=sys.stderr,
        )
        return 1

    run_mcp_server(args.repo)
    return 0


def register(subparsers):
    p = subparsers.add_parser("mcp", help="Run the MCP server (stdio)")
    p.add_argument(
        "--repo",
        default=None,
        help="Path inside the target repository (default: current directory)",
    )
    p.set_defaults(func=run)
