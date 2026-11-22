"""Wake-phrase matching on transcripts: works for any name without training a model."""
from __future__ import annotations

import difflib
import re

FILLERS = {"hey", "hi", "ok", "okay", "yo", "oi", "so", "um", "uh", "hello"}


def _norm(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def match_wake(text: str, wake_words: list[str], window: int = 3) -> tuple[bool, str]:
    """Return (woken, remainder). Looks for a wake word within the first few words."""
    words = _norm(text)
    if not words:
        return False, ""
    targets = [w.lower() for w in wake_words]
    for i, w in enumerate(words[: window + 1]):
        if w in FILLERS:
            continue
        candidates = [w]
        if i + 1 < len(words):
            candidates.append(w + words[i + 1])  # "mal ice" -> "malice"
        for j, cand in enumerate(candidates):
            if any(cand == t or difflib.SequenceMatcher(None, cand, t).ratio() >= 0.8 for t in targets):
                rest_tokens = text.split()
                # Drop the same number of leading raw tokens (fillers + wake word).
                consumed = i + 1 + j
                remainder = " ".join(rest_tokens[consumed:]).lstrip(" ,.!?-")
                return True, remainder
        if i >= window:
            break
    return False, ""
