from robo_cortex.core.assumptions import assumptions_gate


def test_all_phrases_matched_passes():
    gate = assumptions_gate("single-user, local-first", "building a single-user local-first tool")
    assert gate["passed"] is True
    assert gate["fraction_matched"] == 1.0
    assert all(p["matched"] for p in gate["phrases"])


def test_one_unmatched_phrase_fails_default_threshold():
    gate = assumptions_gate(
        "single-user, local-first, low write concurrency",
        "building a single-user local-first tool",
    )
    assert gate["passed"] is False
    assert gate["fraction_matched"] < 1.0
    matched = {p["text"]: p["matched"] for p in gate["phrases"]}
    assert matched["single-user"] is True
    assert matched["local-first"] is True
    assert matched["low write concurrency"] is False


def test_no_assumptions_passes_vacuously():
    gate = assumptions_gate(None, "any task at all")
    assert gate["passed"] is True
    assert gate["fraction_matched"] == 1.0
    assert gate["phrases"] == []

    gate_empty_string = assumptions_gate("", "any task at all")
    assert gate_empty_string["passed"] is True


def test_completely_unrelated_task_fails():
    gate = assumptions_gate("single-user, local-first", "implement a distributed message queue")
    assert gate["passed"] is False
    assert all(not p["matched"] for p in gate["phrases"])


def test_stopwords_stripped_from_phrase_before_matching():
    # "for" and "the" are stopwords; only "shared" and "hosts" must appear
    gate = assumptions_gate("for the shared hosts", "deploying to shared hosts only")
    assert gate["phrases"][0]["matched"] is True


def test_whole_word_matching_not_substring():
    # "user" must not match because the task contains "users" (a different token)
    gate = assumptions_gate("user", "this tool serves multiple users")
    assert gate["phrases"][0]["matched"] is False


def test_hyphenated_phrase_words_split_correctly():
    # tokenization splits on non-word characters, so "single-user" becomes
    # two tokens ("single", "user"), both of which must appear
    gate = assumptions_gate("single-user", "a single deployment per user")
    assert gate["phrases"][0]["matched"] is True

    gate_partial = assumptions_gate("single-user", "a single deployment, no per-user isolation needed")
    # "user" appears (inside "per-user" -> tokenized to "per", "user") and
    # "single" appears -- both present as whole-word tokens
    assert gate_partial["phrases"][0]["matched"] is True
