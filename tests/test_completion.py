import shutil
import subprocess
import sys

import pytest

from robo_cortex.cli.app import build_parser
from robo_cortex.cli.commands import completion


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "robo_cortex.cli", *args],
        capture_output=True,
        text=True,
    )


def test_completion_bash_exits_0():
    result = _run_cli("completion", "bash")
    assert result.returncode == 0
    assert result.stdout.startswith("# roco / robo-cortex bash completion")


def test_completion_bash_registers_both_entry_points():
    result = _run_cli("completion", "bash")
    assert "complete -F _roco_completions roco" in result.stdout
    assert "complete -F _roco_completions robo-cortex" in result.stdout


def test_completion_bash_lists_every_top_level_command():
    """Data-driven: reads the real command surface off the parser, the same
    one `main()` dispatches through, so a future command added to
    ALL_COMMANDS is covered automatically without touching this test.
    """
    parser = build_parser("roco")
    subparsers_action = next(
        action for action in parser._actions
        if hasattr(action, "choices") and action.dest == "command"
    )
    expected_commands = set(subparsers_action.choices)

    script = completion._bash_completion_script()

    for name in expected_commands:
        assert f'\n        {name})\n' in script, f"missing case block for {name!r}"


def test_completion_bash_includes_representative_flags():
    script = completion._bash_completion_script()
    assert "--type" in script
    assert "--scope" in script
    assert "--json" in script
    assert "--add-path" in script


def test_completion_bash_unsupported_shell_rejected_by_argparse():
    result = _run_cli("completion", "zsh")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_completion_bash_output_is_syntactically_valid():
    script = completion._bash_completion_script()
    result = subprocess.run(
        ["bash", "-n"], input=script, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_completion_bash_actually_completes_subcommands_and_flags():
    script = completion._bash_completion_script()
    probe = script + (
        '\n'
        'COMP_WORDS=(roco re)\n'
        'COMP_CWORD=1\n'
        '_roco_completions\n'
        'echo "LEVEL1:${COMPREPLY[@]}"\n'
        'COMP_WORDS=(roco record --t)\n'
        'COMP_CWORD=2\n'
        '_roco_completions\n'
        'echo "LEVEL2:${COMPREPLY[@]}"\n'
    )
    result = subprocess.run(
        ["bash", "-c", probe], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    level1 = next(line for line in lines if line.startswith("LEVEL1:"))
    level2 = next(line for line in lines if line.startswith("LEVEL2:"))
    assert "record" in level1.split(":", 1)[1].split()
    assert "retrieve" in level1.split(":", 1)[1].split()
    assert level2.split(":", 1)[1].split() == ["--type"]
