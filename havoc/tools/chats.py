"""Discord and WhatsApp tools."""
from __future__ import annotations

from typing import Any, Optional

from .common import prepare_message, resolve_attachments, summarize_chat
from .registry import tool

# ---------- Discord ----------


@tool("discord_channels", "List text channels in the batch Discord server.", group="discord")
async def discord_channels(rt: Any) -> str:
    return "Channels: " + ", ".join(f"#{c}" for c in await rt.discord.channels())


@tool("discord_read", "Read recent messages in one Discord channel, or every watched channel if none is given.",
      params={"channel": "Channel name, optional", "hours": "How far back"}, group="discord")
async def discord_read(rt: Any, channel: str = "", hours: float = 24) -> str:
    if channel:
        msgs = await rt.discord.recent(channel, hours)
        title = f"Discord #{channel.lstrip('#')}, last {hours:g}h"
    else:
        msgs = await rt.discord.recent_all(hours)
        title = f"Discord (all watched channels), last {hours:g}h"
    return await summarize_chat(rt, title, [m.line() for m in msgs])


ATTACH_HELP = "Inbox file names to attach (from 'Attached files'), or 'latest'. Optional."


def _log_post(rt: Any, platform: str) -> None:
    log = getattr(rt, "post_log", None)
    if log is None:
        log = rt.post_log = []
    log.append(platform)
    del log[:-20]


@tool("discord_post", "Post in a channel of the batch Discord server. It appears under the user's own name. "
      "Write it as the user, not as Havoc.",
      params={"channel": "Channel name", "message": "Exact text to post", "attachments": ATTACH_HELP},
      confirm=lambda rt, **_: rt.cfg.safety.confirm_discord_post,
      preview=lambda rt, channel="", message="", attachments=None, **_:
          f"Discord #{channel.lstrip('#')}:\n{message}" + (f"\n[+ {', '.join(attachments)}]" if attachments else ""),
      prepare=lambda rt, args: prepare_message(rt, args), group="discord")
async def discord_post(rt: Any, channel: str, message: str = "", attachments: Optional[list[str]] = None) -> str:
    files = resolve_attachments(attachments)
    out = await rt.discord.post(channel, message, files)
    _log_post(rt, "discord")
    return out


# ---------- WhatsApp ----------


@tool("wa_groups", "List the user's WhatsApp groups.", group="whatsapp")
async def wa_groups(rt: Any) -> str:
    groups = await rt.whatsapp.groups()
    return "WhatsApp groups: " + ", ".join(g["name"] for g in groups if g.get("name"))


@tool("wa_read", "Read or summarise recent messages from a WhatsApp group (defaults to the GSA group).",
      params={"group": "Group name, optional (defaults to the GSA group)", "hours": "How far back"},
      group="whatsapp")
async def wa_read(rt: Any, group: str = "", hours: float = 24) -> str:
    g, msgs = await rt.whatsapp.messages(group or None, hours)
    return await summarize_chat(rt, f"WhatsApp '{g['name']}', last {hours:g}h", [m.line() for m in msgs])


@tool("wa_send", "Send a WhatsApp message (and optional photos/files) to a group from the user's own number "
      "(defaults to the GSA group). Write it as the user.",
      params={"message": "Exact text to send (caption when files are attached)", "group": "Group name, optional",
              "attachments": ATTACH_HELP},
      confirm=lambda rt, **_: rt.cfg.safety.confirm_whatsapp_send,
      preview=lambda rt, message="", group="", **_: f"WhatsApp '{group or rt.cfg.whatsapp.group_name}':\n{message}",
      prepare=lambda rt, args: prepare_message(rt, args), group="whatsapp")
async def wa_send(rt: Any, message: str = "", group: str = "", attachments: Optional[list[str]] = None) -> str:
    files = resolve_attachments(attachments)
    out = await rt.whatsapp.send(group or None, message, files)
    _log_post(rt, "whatsapp")
    return out


# ---------- Undo ----------


@tool("undo_last_post", "Delete the most recent Discord post or WhatsApp message Havoc sent (for everyone). "
      "Use when the user says 'undo', 'delete that', 'take it back'. Email can't be unsent.",
      params={"platform": "discord or whatsapp; empty = whichever was posted last"}, group="core")
async def undo_last_post(rt: Any, platform: str = "") -> str:
    log = getattr(rt, "post_log", [])
    target = platform.strip().lower() or (log[-1] if log else "")
    if target.startswith("wa") or target == "whatsapp":
        out = await rt.whatsapp.delete_last()
        target = "whatsapp"
    elif target.startswith("disc"):
        out = await rt.discord.delete_last()
        target = "discord"
    else:
        return "Nothing posted this session to undo."
    if target in log:
        log.reverse()
        log.remove(target)
        log.reverse()
    return out
