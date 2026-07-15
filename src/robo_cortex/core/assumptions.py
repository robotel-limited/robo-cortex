from .text import tokenize, tokenize_without_stopwords

# ARCHITECTURE.md §5.4: deliberately conservative default -- every stated
# assumption phrase must be corroborated by the task text. The mission's
# stated risk is a project-specific win silently becoming a universal rule,
# not the reverse, so the gate defaults strict.
ASSUMPTION_MATCH_THRESHOLD = 1.0


def assumptions_gate(assumptions: str | None, task: str) -> dict:
    """The absolute, assumption-specific gate that decides whether a
    scope-B (global) memory even enters the retrieval candidate set --
    computed once per candidate, before ranking, never as a ranking input.

    A memory with no stated assumptions passes vacuously (fraction 1.0):
    there is nothing to fail to corroborate. Otherwise: split on commas
    into phrases, strip stopwords from each phrase, and require every
    remaining word to appear as a whole word (case-insensitive token
    membership, not substring) in the task text. Binary per phrase, no
    partial credit.
    """
    phrases = [p.strip() for p in (assumptions or "").split(",") if p.strip()]
    if not phrases:
        return {"phrases": [], "fraction_matched": 1.0, "threshold": ASSUMPTION_MATCH_THRESHOLD, "passed": True}

    task_words = set(tokenize(task))
    results = []
    for phrase in phrases:
        phrase_words = tokenize_without_stopwords(phrase)
        matched = all(word in task_words for word in phrase_words) if phrase_words else True
        results.append({"text": phrase, "matched": matched})

    fraction = sum(1 for r in results if r["matched"]) / len(results)
    return {
        "phrases": results,
        "fraction_matched": fraction,
        "threshold": ASSUMPTION_MATCH_THRESHOLD,
        "passed": fraction >= ASSUMPTION_MATCH_THRESHOLD,
    }
