"""Unit tests for the Python token-equivalence check (F6, EVALUATION.md §8).

These test the pure function directly, independent of git/refresh_staleness
plumbing -- test_invalidate.py covers the integrated behavior (reanchoring,
status transitions) using the exact scenarios EVALUATION.md measured.
"""

import pytest

from robo_cortex.core.semantic import python_source_is_semantically_equivalent as equivalent


def test_comment_addition_is_equivalent():
    old = 'def f(x):\n    return x\n'
    new = 'def f(x):\n    # a comment\n    return x\n'
    assert equivalent(old, new) is True


def test_trailing_blank_line_is_equivalent():
    old = 'def f(x):\n    return x\n'
    new = old + "\n"
    assert equivalent(old, new) is True


def test_comment_text_change_is_equivalent():
    """Only the comment's *presence* matters, not its content -- comments
    are dropped entirely from the significant-token stream."""
    old = 'def f(x):\n    # old comment\n    return x\n'
    new = 'def f(x):\n    # completely different comment\n    return x\n'
    assert equivalent(old, new) is True


def test_identical_source_is_equivalent():
    src = 'def f(x):\n    return x\n'
    assert equivalent(src, src) is True


def test_variable_rename_is_not_equivalent():
    old = 'def f(x):\n    return x\n'
    new = 'def f(y):\n    return y\n'
    assert equivalent(old, new) is False


def test_indentation_width_change_is_not_equivalent():
    old = 'if True:\n    x = 1\n'
    new = 'if True:\n        x = 1\n'
    assert equivalent(old, new) is False


def test_logic_change_is_not_equivalent():
    old = 'def f(x):\n    return x + 1\n'
    new = 'def f(x):\n    return x + 2\n'
    assert equivalent(old, new) is False


def test_added_statement_is_not_equivalent():
    old = 'def f(x):\n    return x\n'
    new = 'def f(x):\n    print(x)\n    return x\n'
    assert equivalent(old, new) is False


def test_syntax_error_raises_rather_than_silently_matching():
    """Callers are responsible for catching this and falling back to
    "not equivalent" -- the function itself must not swallow the error."""
    old = 'def f(x):\n    return x\n'
    new = 'def f(x:\n    return x\n'
    with pytest.raises(Exception):
        equivalent(old, new)
