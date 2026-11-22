"""Discord and WhatsApp tools."""
from __future__ import annotations

from typing import Any

from .common import prepare_message, summarize_chat
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


@tool("discord_post", "Post a message in a Discord channel of the batch server. Write it as the user, not as Malice.",
      params={"channel": "Channel name", "message": "Exact text to post"},
      confirm=lambda rt, **_: rt.cfg.safety.confirm_discord_post,
      preview=lambda rt, channel="", message="", **_: f"Discord #{channel.lstrip('#')}:\n{message}",
      prepare=lambda rt, args: prepare_message(rt, args), group="discord")
async def discord_post(rt: Any, channel: str, message: str) -> str:
    return await rt.discord.post(channel, message)


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


@tool("wa_send", "Send a WhatsApp message to a group (defaults to the GSA group). Write it as the user.",
      params={"message": "Exact text to send", "group": "Group name, optional"},
      confirm=lambda rt, **_: rt.cfg.safety.confirm_whatsapp_send,
      preview=lambda rt, message="", group="", **_: f"WhatsApp '{group or rt.cfg.whatsapp.group_name}':\n{message}",
      prepare=lambda rt, args: prepare_message(rt, args), group="whatsapp")
async def wa_send(rt: Any, message: str, group: str = "") -> str:
    return await rt.whatsapp.send(group or None, message)
