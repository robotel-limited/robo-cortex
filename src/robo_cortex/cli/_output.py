"""CLI output formatting utilities."""

import os
import sys

_ANSI_CODES = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
}
_ANSI_RESET = "\033[0m"

# Terminal (superseded/invalidated/abandoned/archived) statuses render red;
# active is green; everything still under review (provisional/needs_review)
# is yellow. Unknown/future status strings pass through uncolored rather
# than raising -- this is display-only, never a source of truth.
_STATUS_COLORS = {
    "active": "green",
    "provisional": "yellow",
    "needs_review": "yellow",
    "superseded": "red",
    "invalidated": "red",
    "abandoned": "red",
    "archived": "red",
}


def _color_enabled(stream) -> bool:
    """NO_COLOR (no-color.org: disable on presence, regardless of value)
    and non-tty output (pipes, redirects, captured subprocess output in
    tests) both suppress color -- only an interactive terminal gets ANSI
    codes.
    """
    if "NO_COLOR" in os.environ:
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def format_status(status: str, *, width: int | None = None, stream=None) -> str:
    """Color-wrap a memory status for terminal display.

    `width` pads the plain text first, then wraps it in the ANSI codes --
    padding after coloring would count the invisible escape bytes toward
    the field width and break column alignment in `list`'s output.
    """
    text = f"{status:<{width}s}" if width else status
    if not _color_enabled(stream or sys.stdout):
        return text
    color = _STATUS_COLORS.get(status)
    if color is None:
        return text
    return f"{_ANSI_CODES[color]}{text}{_ANSI_RESET}"


def _format_score_breakdown(components: dict) -> str:
    """Human-readable --explain / --explain-against output. assumptions_gate
    (present only for scope='global' items, ARCHITECTURE.md §5.4) is a
    nested dict, not a float -- formatted on its own, never blindly run
    through the same `:.3f` as the six numeric components.
    """
    numeric = " ".join(
        f"{key}={value:.3f}" for key, value in components.items()
        if key not in ("total", "assumptions_gate")
    )
    parts = [numeric]
    if "assumptions_gate" in components:
        gate = components["assumptions_gate"]
        phrases = ", ".join(
            f"{p['text']!r}:{'matched' if p['matched'] else 'not matched'}"
            for p in gate["phrases"]
        )
        parts.append(f"assumptions_gate=[{phrases}] passed={gate['passed']}")
    return "  ".join(parts) + f"  total={components['total']:.3f}"
