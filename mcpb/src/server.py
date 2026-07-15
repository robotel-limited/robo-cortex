#!/usr/bin/env python3
"""MCPB entry point: delegates straight to robo-cortex's stdio MCP server.

`uv run` resolves `robo-cortex[mcp]` from PyPI per mcpb/pyproject.toml, so this
file only has to forward the user-configured repo path (or None, to fall back
to the agent's cwd, same as `roco mcp` without --repo).
"""

import sys

from robo_cortex.mcp_server import run

if __name__ == "__main__":
    repo_arg = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    run(repo_arg)
