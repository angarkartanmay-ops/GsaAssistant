"""Mail tools: GSA digest, search, read, draft and send."""
from __future__ import annotations

import email.utils
import re
from typing import Any

from ..brain.llm import parse_json_loose
from ..brain.persona import draft_rules
from ..connectors.gmail_imap import Mail
from .common import blocking, polish_for_others, prepare_message
from .registry import tool

DEADLINE_HINTS = re.compile(r"\b(deadline|due|submit|submission|last date|by (mon|tue|wed|thu|fri|sat|sun)|"
                            r"by \d{1,2}(st|nd|rd|th)?|before \d|reminder|register|rsvp|form)\b", re.I)
NOISE_HINTS = re.compile(r"\b(newsletter|unsubscribe|digest|no-?reply|promotion|webinar recording)\b", re.I)


def heuristic_digest(mails: list[Mail]) -> list[dict]:
    """Keyword fallback when the LLM is unavailable or returns junk."""
    out = []
    for m in mails:
        text = f"{m.subject} {m.body[:800]}"
        if DEADLINE_HINTS.search(text):
            cat = "deadline"
        elif "?" in m.body[:600] or re.search(r"\b(please|kindly|could you|need you)\b", text, re.I):
            cat = "action"
        elif NOISE_HINTS.search(text) or NOISE_HINTS.search(m.sender):
            cat = "noise"
        else:
            cat = "fyi"
        out.append({"id": m.msgid, "category": cat, "summary": m.subject, "due": None})
    return out


async def classify_mails(rt: Any, mails: list[Mail]) -> list[dict]:
    listing = "\n\n".join(m.short(500) for m in mails)
    prompt = (
        "Classify each email for a Google Student Ambassador. Return JSON: "
        '{"items":[{"id":"<id>","category":"deadline|action|fyi|noise","summary":"<max 18 words, '
        'concrete: what, who, when>","due":"<date/time if any, else null>"}]}. '
        "deadline = has a date by which something must be done. action = needs a reply or task, no date. "
        "fyi = useful info. noise = newsletters, automated, irrelevant.\n\n" + listing
    )
    try:
        data = parse_json_loose(await rt.llm.complete(prompt, json_mode=True, temperature=0.1))
        items = data.get("items", data) if isinstance(data, dict) else data
        known = {m.msgid for m in mails}
        items = [i for i in items if isinstance(i, dict) and str(i.get("id")) in known]
        if items:
            return items
    except Exception:  # noqa: BLE001
        pass
    return heuristic_digest(mails)


def format_digest(items: list[dict], mails: list[Mail]) -> str:
    by_id = {m.msgid: m for m in mails}
    order = ["deadline", "action", "fyi", "noise"]
    labels = {"deadline": "DEADLINES", "action": "NEEDS YOUR ACTION", "fyi": "FYI", "noise": "NOISE"}
    lines = []
    for cat in order:
        group = [i for i in items if i.get("category") == cat]
        if not group:
            continue
        lines.append(f"{labels[cat]}:")
        for i in group:
            m = by_id.get(str(i["id"]))
            sender = email.utils.parseaddr(m.sender)[0] or m.sender if m else "?"
            due = f" (due {i['due']})" if i.get("due") else ""
            unread = " [unread]" if m and m.unread else ""
            if cat == "noise":
                lines.append(f"- {sender}: {i.get('summary', '')}")
            else:
                lines.append(f"- [id {i['id']}]{unread} {sender}: {i.get('summary', '')}{due}")
    return "\n".join(lines)


@tool("gsa_mail_digest", "Summarise recent Google Student Ambassador (GSA) emails, grouped into "
      "deadlines, actions, FYI and noise.",
      params={"days": "How many days back to look", "unread_only": "Only unread mail"}, group="mail")
async def gsa_mail_digest(rt: Any, days: int = 3, unread_only: bool = False) -> str:
    mails = await blocking(rt.gmail.gsa_mails, days, unread_only)
    if not mails:
        return f"No GSA mail in the last {days} day(s)" + (" that is unread." if unread_only else ".")
    for m in mails:
        rt.memory.mark_seen("gmail", m.msgid)
    items = await classify_mails(rt, mails)
    return f"{len(mails)} GSA mail(s), last {days} day(s):\n" + format_digest(items, mails)


@tool("search_mail", "Search Gmail with Gmail search syntax (e.g. 'from:priya subject:event newer_than:14d').",
      params={"query": "Gmail search query", "limit": "Max results"}, group="mail")
async def search_mail(rt: Any, query: str, limit: int = 8) -> str:
    mails = await blocking(rt.gmail.search, query, limit)
    if not mails:
        return "No mail matched."
    return "\n\n".join(m.short(300) for m in mails)


@tool("read_mail", "Read one email in full by its id (from a digest or search).",
      params={"mail_id": "The id shown as [id ...]"}, group="mail")
async def read_mail(rt: Any, mail_id: str) -> str:
    m = await blocking(rt.gmail.get, mail_id)
    if not m:
        return f"No mail with id {mail_id}."
    return f"From: {m.sender}\nTo: {m.to}\nDate: {m.date}\nSubject: {m.subject}\n\n{m.body[:3000]}"


@tool("draft_reply", "Write a reply to an email in the user's voice and save it to Gmail Drafts (does not send).",
      params={"mail_id": "Email id", "instructions": "What the reply should say"}, group="mail")
async def draft_reply(rt: Any, mail_id: str, instructions: str) -> str:
    m = await blocking(rt.gmail.get, mail_id)
    if not m:
        return f"No mail with id {mail_id}."
    prompt = (f"Write the body of a reply email from {rt.cfg.assistant.user_name}.\nWhat to say: {instructions}\n\n"
              f"Original from {m.sender}, subject '{m.subject}':\n{m.body[:2500]}\n\n"
              f"Sign off with just the first name '{rt.cfg.assistant.user_name}'.")
    body = await rt.llm.complete(prompt, system=draft_rules(rt.cfg), temperature=0.5)
    body = await polish_for_others(rt, body)
    await blocking(rt.gmail.save_draft, rt.gmail.build_reply(m, body))
    return f"Draft saved in Gmail Drafts, replying to '{m.subject}':\n\n{body}"


def _mail_preview(rt: Any, mail_id: str = "", body: str = "", to: str = "", subject: str = "") -> str:
    if mail_id:
        m = rt.gmail.cache.get(mail_id)
        head = f"Reply to: {m.sender if m else mail_id}\nSubject: Re: {m.subject if m else '?'}"
    else:
        head = f"To: {to}\nSubject: {subject}"
    return f"{head}\n\n{body}"


@tool("send_reply", "Send a reply to an email. The body is exactly what gets sent.",
      params={"mail_id": "Email id", "body": "Full reply text, in the user's voice"},
      confirm=lambda rt, **_: rt.cfg.safety.confirm_email_send,
      preview=lambda rt, mail_id="", body="", **_: _mail_preview(rt, mail_id=mail_id, body=body),
      prepare=lambda rt, args: prepare_message(rt, args, "body"), group="mail")
async def send_reply(rt: Any, mail_id: str, body: str) -> str:
    m = await blocking(rt.gmail.get, mail_id)
    if not m:
        return f"No mail with id {mail_id}."
    await blocking(rt.gmail.send, rt.gmail.build_reply(m, body))
    return f"Reply sent to {m.sender}."


@tool("send_email", "Send a new email.",
      params={"to": "Recipient address", "subject": "Subject line", "body": "Full text, in the user's voice"},
      confirm=lambda rt, **_: rt.cfg.safety.confirm_email_send,
      preview=lambda rt, to="", subject="", body="", **_: _mail_preview(rt, to=to, subject=subject, body=body),
      prepare=lambda rt, args: prepare_message(rt, args, "body"), group="mail")
async def send_email(rt: Any, to: str, subject: str, body: str) -> str:
    if "@" not in to:
        return f"'{to}' isn't an email address."
    await blocking(rt.gmail.send, rt.gmail.build_new(to, subject, body))
    return f"Sent to {to}."
