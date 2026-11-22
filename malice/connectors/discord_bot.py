"""Discord bot that lives in your batch server.

Reads channel history, posts messages, raises alerts on keywords/mentions, and treats DMs
from the owner (you) as commands to Malice, so you can talk to it from your phone.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from ..config import DiscordCfg

log = logging.getLogger("malice.discord")


@dataclass
class DMsg:
    id: int
    channel: str
    author: str
    content: str
    ts: datetime
    mentions_me: bool = False

    def line(self) -> str:
        return f"[{self.ts.astimezone().strftime('%d %b %H:%M')}] #{self.channel} {self.author}: {self.content}"


class DiscordError(RuntimeError):
    pass


class DiscordConnector:
    def __init__(self, cfg: DiscordCfg,
                 on_owner_dm: Optional[Callable[[str], Awaitable[str]]] = None,
                 on_alert: Optional[Callable[[DMsg], Awaitable[None]]] = None):
        self.cfg = cfg
        self.on_owner_dm = on_owner_dm
        self.on_alert = on_alert
        self.client = None
        self.ready = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.error: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.token)

    async def start(self) -> None:
        if not self.configured:
            return
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        client = discord.Client(intents=intents)
        self.client = client

        @client.event
        async def on_ready():  # noqa: ANN202
            log.info("Discord connected as %s", client.user)
            self.ready.set()

        @client.event
        async def on_message(message):  # noqa: ANN001, ANN202
            if message.author == client.user:
                return
            if message.guild is None:
                if self.cfg.owner_user_id and message.author.id == self.cfg.owner_user_id and self.on_owner_dm:
                    async with message.channel.typing():
                        reply = await self.on_owner_dm(message.content)
                    for chunk in _chunks(reply, 1900):
                        await message.channel.send(chunk)
                return
            if self.cfg.guild_id and message.guild.id != self.cfg.guild_id:
                return
            low = message.content.lower()
            mentioned = client.user in message.mentions or (
                self.cfg.owner_user_id and any(u.id == self.cfg.owner_user_id for u in message.mentions))
            if self.on_alert and (mentioned or any(k in low for k in self.cfg.alert_keywords)):
                await self.on_alert(_to_dmsg(message, mentioned))

        async def runner():  # noqa: ANN202
            try:
                await client.start(self.cfg.token)
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                log.error("Discord stopped: %s", self.error)

        self._task = asyncio.create_task(runner())

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def _guild(self):
        if not self.configured:
            raise DiscordError("Discord isn't set up. Put DISCORD_BOT_TOKEN in .env and discord.guild_id in config.yaml.")
        if self.error:
            raise DiscordError(f"Discord bot is down: {self.error}")
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=20)
        except asyncio.TimeoutError as e:
            raise DiscordError("Discord bot hasn't connected yet.") from e
        if self.cfg.guild_id:
            g = self.client.get_guild(self.cfg.guild_id)
            if g:
                return g
        if self.client.guilds:
            return self.client.guilds[0]
        raise DiscordError("The bot isn't in any server. Invite it with the OAuth2 URL from the README.")

    async def channels(self) -> list[str]:
        g = await self._guild()
        return [c.name for c in g.text_channels]

    async def _channel(self, name: str):
        g = await self._guild()
        name = (name or self.cfg.default_channel).lstrip("#").lower().strip()
        chans = g.text_channels
        for c in chans:
            if c.name.lower() == name:
                return c
        for c in chans:
            if name in c.name.lower():
                return c
        raise DiscordError(f"No channel like #{name}. Channels: {', '.join(c.name for c in chans)}")

    async def recent(self, channel: str, hours: float = 24, limit: int = 80) -> list[DMsg]:
        ch = await self._channel(channel)
        after = datetime.now(timezone.utc) - timedelta(hours=hours)
        out = []
        async for m in ch.history(limit=limit, after=after, oldest_first=True):
            if m.content or m.attachments:
                out.append(_to_dmsg(m, False))
        return out

    async def recent_all(self, hours: float = 24, per_channel: int = 40) -> list[DMsg]:
        g = await self._guild()
        names = self.cfg.watch_channels or [c.name for c in g.text_channels]
        msgs: list[DMsg] = []
        for n in names:
            try:
                msgs.extend(await self.recent(n, hours, per_channel))
            except Exception as e:  # noqa: BLE001 - missing perms on a channel
                log.debug("skip #%s: %s", n, e)
        return sorted(msgs, key=lambda m: m.ts)

    async def post(self, channel: str, text: str) -> str:
        ch = await self._channel(channel)
        sent = None
        for chunk in _chunks(text, 1900):
            sent = await ch.send(chunk)
        return f"Posted in #{ch.name}" + (f" ({sent.jump_url})" if sent else "")


def _to_dmsg(m, mentioned: bool) -> DMsg:  # noqa: ANN001
    content = m.clean_content if hasattr(m, "clean_content") else m.content
    if getattr(m, "attachments", None):
        content += " " + " ".join(f"[attachment: {a.filename}]" for a in m.attachments)
    return DMsg(m.id, getattr(m.channel, "name", "dm"), m.author.display_name, content.strip(),
                m.created_at, mentioned)


def _chunks(text: str, n: int) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]
