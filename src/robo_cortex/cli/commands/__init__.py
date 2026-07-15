"""CLI commands registry."""

# Import all command modules
from robo_cortex.cli.commands import (
    init,
    record,
    show,
    list_cmd,
    retrieve,
    search,
    affected,
    status,
    evidence,
    link,
    mcp,
    transfer,
    hooks,
    completion,
)

ALL_COMMANDS = [
    init,
    record,
    show,
    list_cmd,
    retrieve,
    search,
    affected,
    status,
    evidence,
    link,
    mcp,
    transfer,
    hooks,
    completion,
]
