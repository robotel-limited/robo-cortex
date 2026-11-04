"""L0 abstract tier: a short LLM-generated one-line summary of a memory's
statement, computed synchronously at record_memory() time via a local
Ollama model. Same fail-open reference pattern as
/srv/robo-assistant/robo_assistant/classify/translate.py::to_english --
any failure (model not pulled, Ollama down, timeout, bad response shape)
falls back to None, never raises: an abstract is a nice-to-have index aid,
not a thing a write should ever fail over.
"""
from __future__ import annotations

import httpx

DEFAULT_MODEL = "lfm2.5:350m"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 10.0
ABSTRACT_MAX_CHARS = 200


def generate_abstract(
    text: str, *, model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    if not text or not text.strip():
        return None
    prompt = (
        "Summarize the following in one short sentence (max 25 words), "
        "plain text, no notes, quotes, or explanations.\n\n"
        f"Text: {text}"
    )
    try:
        resp = httpx.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        abstract = resp.json()["response"].strip()
        if not abstract:
            return None
        return abstract[:ABSTRACT_MAX_CHARS]
    except Exception:
        return None
