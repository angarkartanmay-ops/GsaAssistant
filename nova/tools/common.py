"""Helpers shared by tools."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Optional

from ..brain.antislop import polish
from ..brain.persona import draft_rules
from ..config import inbox_dir

RAW_LIMIT = 2800


async def blocking(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)


async def summarize_chat(rt: Any, title: str, lines: list[str], focus: str = "") -> str:
    """Return raw lines if they fit, otherwise a compact LLM summary of them."""
    if not lines:
        return f"{title}: nothing new."
    raw = "\n".join(lines)
    if len(raw) <= RAW_LIMIT:
        return f"{title} ({len(lines)} messages):\n{raw}"
    user = rt.cfg.assistant.user_name
    prompt = (
        f"Summarise this chat log for {user}, a Google Student Ambassador. Output plain short lines "
        f"under these labels, skipping empty ones: DEADLINES (with dates), ASKS FOR {user.upper()}, "
        f"DECISIONS/ANNOUNCEMENTS, LINKS/FORMS, OTHER (one line max). Quote exact dates, times, "
        f"names and links. Ignore greetings, stickers and banter. {focus}\n\n{raw[-12000:]}"
    )
    summary = await rt.llm.complete(prompt, temperature=0.2)
    return f"{title} ({len(lines)} messages, summarised):\n{summary.strip()}"


async def polish_for_others(rt: Any, text: str) -> str:
    return await polish(text, rt.llm, draft_rules(rt.cfg))


async def prepare_message(rt: Any, args: dict, key: str = "message") -> dict:
    if args.get(key):
        args[key] = await polish_for_others(rt, args[key])
    return args


class AttachmentError(ValueError):
    pass


def latest_inbox_files(n: int = 1) -> list[Path]:
    files = sorted((p for p in inbox_dir().iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
    return files[-n:] if files else []


def resolve_attachments(names: Optional[list[str]]) -> list[Path]:
    """Map attachment names from the model to files in data/inbox. Anything outside is refused,
    so a misheard request can never mail out arbitrary files from the PC."""
    if not names:
        return []
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    root = inbox_dir().resolve()
    out: list[Path] = []
    for raw in names:
        name = str(raw).strip().strip("'\"")
        if name.lower() in {"latest", "last", "last photo", "latest photo", "the photo", "photo"}:
            out += latest_inbox_files(1)
            continue
        p = Path(name)
        cand = (p if p.is_absolute() else root / p.name).resolve()
        if root not in cand.parents:
            raise AttachmentError(f"'{name}' isn't in the inbox; only files sent from the phone can be attached.")
        if not cand.exists():
            matches = [f for f in root.iterdir() if f.name.endswith(p.name)]
            if not matches:
                raise AttachmentError(f"No inbox file called '{p.name}'.")
            cand = sorted(matches, key=lambda f: f.stat().st_mtime)[-1]
        out.append(cand)
    return out


def describe_attachments(files: list[Path]) -> str:
    return (" with " + ", ".join(re.sub(r"^\d{10,}_", "", f.name) for f in files)) if files else ""
