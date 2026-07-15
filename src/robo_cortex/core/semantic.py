"""Comment/whitespace-tolerant equivalence check for Python source.

EVALUATION.md §8 measured a 100% spurious `needs_review` rate on
non-semantic edits (a comment addition, a trailing blank line) because
`refresh_staleness` compares exact git blob hashes (ARCHITECTURE.md §5.3):
it cannot tell "the file changed" from "the file changed in a way that
matters." This module narrows that gap for Python specifically, using the
stdlib tokenizer rather than a whitespace-blind text diff -- indentation is
semantic in Python (`git diff -w` was explicitly rejected as a fix for this
reason), so INDENT/DEDENT tokens are kept in the comparison; only COMMENT
and NL (blank-line / comment-line) tokens are dropped.

Fail-safe, not fail-silent: any tokenization failure (syntax error,
mismatched encoding, a non-Python file that merely ends in .py) is treated
as "cannot prove equivalence" -- the caller falls back to flagging the
memory for review, the same as it would have before this module existed.
"""

import io
import tokenize

_IGNORED_TOKEN_TYPES = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING}


def _significant_tokens(source: str) -> list[tuple]:
    """Tokenize `source`, keeping only tokens that affect meaning.

    Position info (line/column) is dropped from the comparison on purpose:
    a comment added earlier in the file shifts every subsequent token's
    line number without changing what any of them mean.
    """
    tokens = []
    readline = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type in _IGNORED_TOKEN_TYPES:
            continue
        tokens.append((tok.type, tok.string))
    return tokens


def python_source_is_semantically_equivalent(old_source: str, new_source: str) -> bool:
    """True if `old_source` and `new_source` tokenize to the same
    significant-token stream -- i.e. the only differences are comments
    and/or blank lines. Raises on any tokenization failure (malformed
    source, incomplete input); callers must treat that as "unknown, not
    equivalent" rather than let it propagate as a crash.
    """
    return _significant_tokens(old_source) == _significant_tokens(new_source)
