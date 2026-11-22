"""Discord bot that lives in your batch server.

Reads channel history, posts messages, raises alerts on keywords/mentions, and treats DMs
from the owner (you) as commands to Havoc, so you can talk to it from your phone.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .. import config as config_mod
from ..config import DiscordCfg, inbox_dir

log = logging.getLogger("havoc.discord")
WEBHOOK_NAME = "HAVOC relay"
AUDIO_EXT = {".ogg", ".oga", ".mp3", ".m4a", ".wav", ".webm", ".opus", ".aac"}
# (text, attached files, voice note) -> (reply text, optional spoken reply file)
OwnerDM = Callable[[str, list[Path], Optional[Path]], Awaitable[tuple[str, Optional[Path]]]]


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
                 on_owner_dm: Optional[OwnerDM] = None,
                 on_alert: Optional[Callable[[DMsg], Awaitable[None]]] = None,
                 default_name: str = ""):
        self.cfg = cfg
        self.on_owner_dm = on_owner_dm
        self.on_alert = on_alert
        self.default_name = default_name
        self.client = None
        self.ready = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.error: Optional[str] = None
        self._avatar_url: Optional[str] = None
        self.sent: list[Any] = []  # recent messages we posted, newest last, for undo

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
            if message.author == client.user or message.webhook_id is not None:
                return  # our own posts (bot or "as you" webhook) never trigger alerts
            if message.guild is None:
                if self.on_owner_dm and self.is_owner(message.author):
                    await self._handle_owner_dm(message)
                return
            if self.cfg.guild_id and message.guild.id != self.cfg.guild_id:
                return
            low = message.content.lower()
            mentioned = client.user in message.mentions or (
                self.owner_id and any(u.id == self.owner_id for u in message.mentions))
            if self.on_alert and (mentioned or any(k in low for k in self.cfg.alert_keywords)):
                await self.on_alert(_to_dmsg(message, mentioned))

        async def runner():  # noqa: ANN202
            try:
                await client.start(self.cfg.token)
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                log.error("Discord stopped: %s", self.error)

        self._task = asyncio.create_task(runner())

    # ---------- who is the owner ----------
    @property
    def _owner_file(self) -> Path:
        return config_mod.DATA_DIR / "discord_owner_id"

    @property
    def owner_id(self) -> int:
        """Your numeric Discord ID: from config, or locked in the first time your username DMs."""
        if self.cfg.owner_user_id:
            return self.cfg.owner_user_id
        try:
            return int(self._owner_file.read_text().strip())
        except (OSError, ValueError):
            return 0

    def is_owner(self, user) -> bool:  # noqa: ANN001
        if self.owner_id:
            return user.id == self.owner_id
        # No ID yet: match the username once, then lock onto that account's ID for good, so a
        # different account that later takes the same username can't pose as you.
        wanted = self.cfg.owner_username.strip().lstrip("@").lower()
        if wanted and str(getattr(user, "name", "")).lower() == wanted:
            self._owner_file.parent.mkdir(parents=True, exist_ok=True)
            self._owner_file.write_text(str(user.id))
            log.info("Discord owner locked to %s (%s)", user.name, user.id)
            return True
        return False

    async def _handle_owner_dm(self, message) -> None:  # noqa: ANN001
        """Your phone line: text, photos/files (saved to the inbox) and voice notes."""
        import discord
        files: list[Path] = []
        voice: Optional[Path] = None
        for a in message.attachments:
            dest = inbox_dir() / f"{int(time.time())}_{_safe_name(a.filename)}"
            await a.save(dest)
            is_audio = (a.content_type or "").startswith("audio/") or dest.suffix.lower() in AUDIO_EXT
            if is_audio and voice is None:
                voice = dest
            else:
                files.append(dest)
        async with message.channel.typing():
            reply, audio = await self.on_owner_dm(message.content or "", files, voice)
        chunks = _chunks(reply, 1900)
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            if last and audio is not None:
                await message.channel.send(chunk, file=discord.File(str(audio), filename="havoc.wav"))
            else:
                await message.channel.send(chunk)

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
        name = (name or self.cfg.default_channel).strip()
        # Accept a channel ID, a <#mention> or a discord.com/channels/<server>/<channel> link too.
        m = re.search(r"(\d{15,22})\D*$", name)
        if m and (name.isdigit() or "discord.com/channels/" in name or name.startswith("<#")):
            ch = g.get_channel(int(m.group(1)))
            if ch is not None and hasattr(ch, "send"):
                return ch
            raise DiscordError(f"Channel {m.group(1)} isn't in the server or the bot can't see it.")
        name = name.lstrip("#").lower()
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

    async def _webhook(self, ch):  # noqa: ANN001, ANN202
        for wh in await ch.webhooks():
            if wh.name == WEBHOOK_NAME and wh.user and wh.user.id == self.client.user.id:
                return wh
        return await ch.create_webhook(name=WEBHOOK_NAME, reason="Posts on behalf of the server owner")

    async def _avatar(self) -> Optional[str]:
        if self.cfg.post_as_avatar:
            return self.cfg.post_as_avatar
        if self._avatar_url is None and self.owner_id:
            try:
                user = await self.client.fetch_user(self.owner_id)
                self._avatar_url = str(user.display_avatar.url)
            except Exception:  # noqa: BLE001
                self._avatar_url = ""
        return self._avatar_url or None

    async def post(self, channel: str, text: str, files: Optional[list[Path]] = None) -> str:
        """Post as you (webhook with your name + avatar); falls back to the bot account."""
        import discord
        ch = await self._channel(channel)
        files = files or []
        chunks = _chunks(text, 1900) if text else [""]
        name = self.cfg.post_as_name or self.default_name or None
        how = "as the bot"
        sent = None
        wh = None
        if self.cfg.post_as_webhook:
            try:
                wh = await self._webhook(ch)
            except discord.Forbidden:
                log.warning("No Manage Webhooks permission in #%s; posting as the bot", ch.name)
        for i, chunk in enumerate(chunks):
            dfiles = [discord.File(str(f), filename=_display(f)) for f in files] if i == len(chunks) - 1 else []
            if wh is not None:
                sent = await wh.send(chunk, username=name, avatar_url=await self._avatar(), files=dfiles, wait=True)
                how = f"as {name}" if name else "via webhook"
            else:
                sent = await ch.send(chunk, files=dfiles)
            self._remember(sent)
        extra = f" with {len(files)} file{'s' if len(files) != 1 else ''}" if files else ""
        return f"Posted in #{ch.name} {how}{extra}" + (f" ({sent.jump_url})" if sent else "")

    def _remember(self, msg) -> None:  # noqa: ANN001
        if msg is not None:
            self.sent = (self.sent + [msg])[-20:]

    async def delete_last(self) -> str:
        if not self.sent:
            return "Nothing I posted on Discord to take back."
        msg = self.sent.pop()
        await msg.delete()
        return f"Deleted my last Discord post in #{getattr(msg.channel, 'name', '?')}."


def _to_dmsg(m, mentioned: bool) -> DMsg:  # noqa: ANN001
    content = m.clean_content if hasattr(m, "clean_content") else m.content
    if getattr(m, "attachments", None):
        content += " " + " ".join(f"[attachment: {a.filename}]" for a in m.attachments)
    return DMsg(m.id, getattr(m.channel, "name", "dm"), m.author.display_name, content.strip(),
                m.created_at, mentioned)


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[-80:] or "file"


def _display(f: Path) -> str:
    return re.sub(r"^\d{10,}_", "", f.name)


def _chunks(text: str, n: int) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]
