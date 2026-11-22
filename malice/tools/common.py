"""Helpers shared by tools."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..brain.antislop import polish
from ..brain.persona import draft_rules

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
