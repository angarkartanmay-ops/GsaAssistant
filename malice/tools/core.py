"""Memory, reminders and the daily briefing."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import dateparser

from .common import summarize_chat
from .registry import tool


@tool("remember", "Save a durable fact about the user, their GSA work or people they work with.",
      params={"fact": "The fact, as a short sentence"}, group="core")
async def remember(rt: Any, fact: str) -> str:
    rt.memory.remember(fact)
    return f"Remembered: {fact}"


@tool("forget", "Delete remembered facts containing some words.",
      params={"what": "Words the fact contains"}, group="core")
async def forget(rt: Any, what: str) -> str:
    n = rt.memory.forget(what)
    return f"Forgot {n} fact(s)." if n else "Nothing matched."


def parse_when(when: str) -> datetime | None:
    return dateparser.parse(when, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False})


@tool("remind_me", "Set a reminder. Malice will speak and notify at that time.",
      params={"when": "Plain words: 'in 20 minutes', 'tomorrow 9am', 'friday 6pm'",
              "text": "What to remind about"}, group="core")
async def remind_me(rt: Any, when: str, text: str) -> str:
    dt = parse_when(when)
    if dt is None:
        return f"Couldn't understand the time '{when}'."
    if dt.timestamp() < time.time() - 60:
        return f"'{when}' resolves to {dt:%d %b %H:%M}, which is in the past."
    rid = rt.memory.add_reminder(dt.timestamp(), text)
    return f"Reminder #{rid} set for {dt:%a %d %b, %H:%M}: {text}"


@tool("list_reminders", "List upcoming reminders.", params={"days": "How many days ahead"}, group="core")
async def list_reminders(rt: Any, days: int = 7) -> str:
    rows = rt.memory.upcoming_reminders(days * 86400)
    if not rows:
        return "No reminders coming up."
    return "\n".join(f"#{rid} {datetime.fromtimestamp(ts):%a %d %b %H:%M}: {text}" for rid, ts, text in rows)


async def gather_briefing(rt: Any, hours: float = 16) -> str:
    """Collect everything for a briefing. Each source fails independently."""
    sections: list[str] = [f"Now: {datetime.now():%A %d %B, %H:%M}"]

    async def section(name: str, coro) -> None:  # noqa: ANN001
        try:
            sections.append(await coro)
        except Exception as e:  # noqa: BLE001
            sections.append(f"{name}: unavailable ({e})")

    from .dashboard import dashboard_tasks
    from .gmail import gsa_mail_digest

    if rt.gmail.configured:
        await section("Mail", gsa_mail_digest(rt, days=2))
    await section("Tasks", dashboard_tasks(rt, refresh=False) if rt.dashboard.configured else list_tasks_text(rt))
    rem = rt.memory.upcoming_reminders(86400)
    if rem:
        sections.append("Reminders today: " + "; ".join(f"{datetime.fromtimestamp(ts):%H:%M} {t}" for _, ts, t in rem))
    if rt.whatsapp.configured:
        async def wa() -> str:
            g, msgs = await rt.whatsapp.messages(None, hours)
            return await summarize_chat(rt, f"WhatsApp '{g['name']}'", [m.line() for m in msgs])
        await section("WhatsApp", wa())
    if rt.discord.configured:
        async def dc() -> str:
            msgs = await rt.discord.recent_all(hours)
            return await summarize_chat(rt, "Discord", [m.line() for m in msgs])
        await section("Discord", dc())
    return "\n\n".join(sections)


async def list_tasks_text(rt: Any) -> str:
    tasks = rt.memory.tasks()
    return "Tasks:\n" + ("\n".join(t.line() for t in tasks) if tasks else "none")


@tool("daily_briefing", "Catch the user up on everything GSA: mail, dashboard tasks, reminders, "
      "WhatsApp group and Discord. Use for 'brief me', 'what did I miss', 'morning update'.",
      params={"hours": "How far back to look in chats"}, group="core")
async def daily_briefing(rt: Any, hours: float = 16) -> str:
    data = await gather_briefing(rt, hours)
    return ("Briefing data follows. Lead with the nearest deadline, then actions, then anything "
            "notable in the chats. Skip empty sections.\n\n" + data)

