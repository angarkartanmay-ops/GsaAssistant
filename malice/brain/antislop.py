"""Detect and remove the phrases that make text read as machine-written filler.

Two layers:
1. `light_clean` - deterministic: strips sycophantic openers, canned closers, emoji spam and
   em-dash chains. Applied to every reply.
2. `polish` - if hits remain in text that other people will read (mail, Discord, WhatsApp),
   ask the LLM for one rewrite with the hits listed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# (pattern, label). Case-insensitive, matched on word boundaries where it makes sense.
SLOP_PATTERNS: list[tuple[str, str]] = [
    (r"\bas an ai( language model)?\b", "as an AI"),
    (r"\bi hope (this|my) (e-?mail|message|note) finds you well\b", "hope this finds you well"),
    (r"\bi hope you('| a)re (doing )?well\b", "hope you're well"),
    (r"\bgreat question\b", "great question"),
    (r"\bi'?d be (happy|glad|delighted) to\b", "I'd be happy to"),
    (r"\bdelv(e|es|ed|ing)\b", "delve"),
    (r"\btapestry\b", "tapestry"),
    (r"\b(a )?testament to\b", "testament to"),
    (r"\bnavigat(e|ing) the (complexities|landscape|world)\b", "navigate the complexities"),
    (r"\bin today'?s (fast-paced|digital|ever-changing) (world|age|landscape)\b", "in today's fast-paced world"),
    (r"\bit'?s (important|worth|crucial) to (note|remember|mention)\b", "it's important to note"),
    (r"\b(elevate|supercharge|unleash|unlock) (your|the|our)\b", "hype verb"),
    (r"\bseamless(ly)?\b", "seamless"),
    (r"\bgame[- ]changer\b", "game-changer"),
    (r"\b(feel free to|don'?t hesitate to)\b", "feel free to"),
    (r"\b(please )?let me know if (you (need|have)|there'?s) (anything|any(thing)? else|any (other |further )?questions)\b", "let me know if..."),
    (r"\bi hope (this|that) helps\b", "I hope this helps"),
    (r"\bin conclusion\b", "in conclusion"),
    (r"\bembark(ing)? on (a|this|our) journey\b", "journey"),
    (r"\b(rest assured|without further ado)\b", "filler"),
    (r"\bever-evolving\b", "ever-evolving"),
    (r"\bfoster(ing)? (a )?(sense of )?(community|collaboration)\b", "foster community"),
    (r"\bvibrant\b", "vibrant"),
    (r"\bleverag(e|ing)\b", "leverage"),
]

OPENER_RE = re.compile(
    r"^\s*(certainly|absolutely|of course|sure thing|great question|excellent question|"
    r"what a great question|good question|i'?d be (happy|glad) to help( with that)?|"
    r"happy to help)[!.,]*\s*",
    re.I,
)
CLOSER_RE = re.compile(
    r"\s*(\n|^|(?<=[.!?]))\s*((please )?(let me know|feel free|don'?t hesitate)[^.!?\n]*"
    r"(anything else|questions|help|assist|further)[^.!?\n]*[.!?]?|i hope (this|that) helps[.!]?)\s*$",
    re.I,
)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F2FF☀-⛿]")


@dataclass
class Hit:
    label: str
    match: str


def find_slop(text: str) -> list[Hit]:
    hits: list[Hit] = []
    for pat, label in SLOP_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            hits.append(Hit(label, m.group(0)))
    if OPENER_RE.match(text):
        hits.append(Hit("sycophantic opener", OPENER_RE.match(text).group(0).strip()))
    if text.count("—") >= 3:
        hits.append(Hit("em-dash chain", "— x" + str(text.count("—"))))
    if len(EMOJI_RE.findall(text)) >= 3:
        hits.append(Hit("emoji spam", "".join(EMOJI_RE.findall(text))[:10]))
    return hits


def light_clean(text: str, allow_emoji: bool = False) -> str:
    """Deterministic cleanup that never changes meaning."""
    if not text:
        return text
    out = OPENER_RE.sub("", text, count=1)
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    out = CLOSER_RE.sub("", out).rstrip()
    if out.count("—") >= 2:
        out = re.sub(r"\s*—\s*", ", ", out)
    if not allow_emoji and len(EMOJI_RE.findall(out)) >= 3:
        out = EMOJI_RE.sub("", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip() or text.strip()


def for_speech(text: str) -> str:
    """Strip markdown and URLs so TTS doesn't read symbols aloud."""
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"https?://\S+", "the link", t)
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    t = EMOJI_RE.sub("", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\.\s*\.", ".", t)
    return re.sub(r"\s{2,}", " ", t).strip()


async def polish(text: str, llm: Any, rules: str) -> str:
    """Clean text meant for other people. One LLM rewrite at most, only if hits remain."""
    cleaned = light_clean(text, allow_emoji=True)
    hits = find_slop(cleaned)
    if not hits or llm is None:
        return cleaned
    listed = ", ".join(sorted({h.match for h in hits}))
    prompt = (f"Rewrite this message so it reads like a real person wrote it. Remove these phrases "
              f"and anything like them: {listed}. Keep every fact, name, date and link. Keep it about "
              f"the same length or shorter. Output only the rewritten message.\n\n---\n{cleaned}\n---")
    try:
        rewritten = (await llm.complete(prompt, system=rules, temperature=0.4)).strip().strip("-").strip()
    except Exception:  # noqa: BLE001
        return cleaned
    if not rewritten or len(find_slop(rewritten)) >= len(hits):
        return cleaned
    return light_clean(rewritten, allow_emoji=True)
