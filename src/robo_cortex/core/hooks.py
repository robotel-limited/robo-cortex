"""Git hook management: the enforcement/reporting layers robo-cortex ships.

Per raport-oportunitate.md's audit, the pre-0.3.0 README described three
enforcement layers -- git hooks, a `@requires_memory_check` decorator, and
a CI/CD gate -- none of which existed in code. This module builds the
first one for real: a pre-commit hook that blocks a commit touching paths
linked to non-terminal memories until they've been reviewed. The decorator
and CI-gate stay on ROADMAP.md; see that file for why they aren't built
yet.

Bypass is explicit and documented, not hidden: `git commit --no-verify`
skips any pre-commit hook, robo-cortex's included. The pitch this earns is
"enforcement by default, bypass explicit" -- true, unlike the old "can't
skip, no bypass" claim.

A second, optional hook (post-commit) was added later: purely
informational, never blocking (the commit it reports on already
happened by the time it runs) -- see `_post_commit_hook_block`.
"""

import shutil
import stat
import subprocess
import sys
from pathlib import Path

from .errors import ValidationError

HOOK_FILENAME = "pre-commit"
POST_COMMIT_HOOK_FILENAME = "post-commit"
MARKER_START = "# >>> robo-cortex pre-commit hook >>>"
MARKER_END = "# <<< robo-cortex pre-commit hook <<<"
POST_COMMIT_MARKER_START = "# >>> robo-cortex post-commit hook >>>"
POST_COMMIT_MARKER_END = "# <<< robo-cortex post-commit hook <<<"

_MARKERS = {
    HOOK_FILENAME: (MARKER_START, MARKER_END),
    POST_COMMIT_HOOK_FILENAME: (POST_COMMIT_MARKER_START, POST_COMMIT_MARKER_END),
}


def _is_valid_roco_binary(path: str) -> bool:
    """Verify that a candidate binary is actually robo-cortex by running --version."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout + result.stderr).lower()
        return "roco" in output or "robo-cortex" in output
    except (OSError, subprocess.TimeoutExpired):
        return False


def _roco_invocation() -> str:
    """Absolute command to invoke robo-cortex from inside the hook.

    Resolved at install time rather than relying on PATH inside git's hook
    execution environment (which isn't always the same as an interactive
    shell's PATH, e.g. GUI git clients): prefer an installed `roco`/
    `robo-cortex` script if one is on PATH (verified to be ours), otherwise
    fall back to `sys.executable -m robo_cortex.cli` so the hook keeps
    working even from an editable/dev install without a console-script
    entry point.
    """
    for candidate in [shutil.which("roco"), shutil.which("robo-cortex")]:
        if candidate and _is_valid_roco_binary(candidate):
            return candidate
    return f"{sys.executable} -m robo_cortex.cli"


def _hook_block(roco_cmd: str, hook_name: str = HOOK_FILENAME) -> str:
    if hook_name == POST_COMMIT_HOOK_FILENAME:
        return _post_commit_hook_block(roco_cmd)

    marker_start, marker_end = _MARKERS[hook_name]
    return (
        f"{marker_start}\n"
        "# Installed by `roco hooks install`. Blocks a commit that touches\n"
        "# paths linked to active/provisional/needs_review memories, until\n"
        "# they've been reviewed. Bypass explicitly with: git commit --no-verify\n"
        f'ROCO_CMD="{roco_cmd}"\n'
        'if ! test -x "$ROCO_CMD"; then\n'
        '  echo "robo-cortex pre-commit hook: robo-cortex binary not found" >&2\n'
        '  echo "Reinstall with: roco hooks install" >&2\n'
        '  echo "To bypass this check: git commit --no-verify" >&2\n'
        "  exit 0\n"
        "fi\n"
        '"$ROCO_CMD" hooks check\n'
        'STATUS=$?\n'
        'if [ "$STATUS" -ne 0 ]; then exit "$STATUS"; fi\n'
        f"{marker_end}\n"
    )


def _post_commit_hook_block(roco_cmd: str) -> str:
    """Informational report, run after the commit already exists -- so
    unlike the pre-commit block, this always exits 0. `HEAD~1` doesn't
    exist for a repo's very first commit, so that case is skipped
    entirely rather than letting `git rev-parse` fail noisily.
    """
    marker_start, marker_end = _MARKERS[POST_COMMIT_HOOK_FILENAME]
    return (
        f"{marker_start}\n"
        "# Installed by `roco hooks install --post-commit`. Informational\n"
        "# only -- reports memories put at risk by the commit that just\n"
        "# happened; never blocks (the commit already exists by the time\n"
        "# this runs). Uninstall with: roco hooks uninstall --post-commit\n"
        f'ROCO_CMD="{roco_cmd}"\n'
        'if ! test -x "$ROCO_CMD"; then\n'
        "  exit 0\n"
        "fi\n"
        'if ! git rev-parse -q --verify HEAD~1 > /dev/null 2>&1; then\n'
        "  exit 0\n"
        "fi\n"
        '"$ROCO_CMD" affected --diff-range HEAD~1..HEAD\n'
        "exit 0\n"
        f"{marker_end}\n"
    )


def hook_path(repo_root: Path, hook_name: str = HOOK_FILENAME) -> Path:
    return repo_root / ".git" / "hooks" / hook_name


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install(repo_root: Path, *, force: bool = False, hook_name: str = HOOK_FILENAME) -> dict:
    """Install a hook (pre-commit by default, or post-commit).

    A pre-existing, non-robo-cortex hook at the same filename is refused
    unless force=True, in which case the existing hook's content is
    preserved and chained: it runs first, robo-cortex's block runs after
    -- neither hook silently disappears.
    """
    path = hook_path(repo_root, hook_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    roco_cmd = _roco_invocation()
    marker_start, _marker_end = _MARKERS[hook_name]

    if path.exists():
        existing = path.read_text()
        if marker_start in existing:
            # Already ours -- reinstalling just refreshes roco_cmd resolution
            # and the block content, in case the install location moved.
            before = existing[: existing.index(marker_start)]
            path.write_text(before + _hook_block(roco_cmd, hook_name))
            _make_executable(path)
            return {"installed": True, "chained": bool(_non_shebang_lines(before)), "path": str(path)}
        if not force:
            raise ValidationError(
                f"{path} already exists and isn't a robo-cortex hook -- "
                "use --force to chain it (your existing hook runs first, "
                "robo-cortex's check runs after)"
            )
        chained = existing.rstrip("\n") + "\n\n" + _hook_block(roco_cmd, hook_name)
        path.write_text(chained)
        _make_executable(path)
        return {"installed": True, "chained": True, "path": str(path)}

    path.write_text("#!/bin/sh\n" + _hook_block(roco_cmd, hook_name))
    _make_executable(path)
    return {"installed": True, "chained": False, "path": str(path)}


def uninstall(repo_root: Path, *, hook_name: str = HOOK_FILENAME) -> dict:
    """Remove robo-cortex's block from a hook. If nothing but the block
    (and a shebang) remains, delete the file entirely; if a chained
    hook's own content remains, leave it in place.
    """
    path = hook_path(repo_root, hook_name)
    if not path.exists():
        return {"uninstalled": False, "reason": f"no {hook_name} hook is present"}

    marker_start, marker_end = _MARKERS[hook_name]
    content = path.read_text()
    if marker_start not in content or marker_end not in content:
        return {"uninstalled": False, "reason": f"the existing {hook_name} hook isn't robo-cortex's"}

    start = content.index(marker_start)
    end = content.index(marker_end) + len(marker_end)
    remainder = content[:start] + content[end:]

    if not _non_shebang_lines(remainder):
        path.unlink()
        return {"uninstalled": True, "path": str(path), "deleted": True}

    path.write_text(remainder)
    _make_executable(path)
    return {"uninstalled": True, "path": str(path), "deleted": False}


def status(repo_root: Path, *, hook_name: str = HOOK_FILENAME) -> dict:
    path = hook_path(repo_root, hook_name)
    if not path.exists():
        return {"installed": False, "path": str(path)}
    marker_start, _marker_end = _MARKERS[hook_name]
    content = path.read_text()
    if marker_start not in content:
        return {
            "installed": False, "path": str(path),
            "note": f"a {hook_name} hook exists but isn't robo-cortex's",
        }
    before = content[: content.index(marker_start)]
    return {"installed": True, "path": str(path), "chained": bool(_non_shebang_lines(before))}


def _non_shebang_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#!/")]
