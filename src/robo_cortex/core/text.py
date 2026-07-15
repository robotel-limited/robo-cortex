import re

# ARCHITECTURE.md §5.4's stopword list -- shared here rather than duplicated
# because Stage 8's assumption-phrase gate uses the exact same set.
STOPWORDS = {
    "a", "an", "the", "for", "with", "is", "are", "of", "to", "in", "on", "and", "or",
}


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def tokenize_without_stopwords(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOPWORDS]


def fts_query_string(text: str) -> str:
    """Quote every token so free text can never be parsed as FTS5 query
    syntax (a bare hyphen, colon, or quote must never turn into a NOT /
    column-filter / phrase operator -- see the assumptions-matching bug
    this exact failure caused during Gate B review). Stopwords are dropped
    so a common word like "the" doesn't make every memory in the store
    match. Shared by retrieve, search, and duplicate detection.
    """
    tokens = tokenize_without_stopwords(text)
    return " OR ".join(f'"{token}"' for token in tokens)
