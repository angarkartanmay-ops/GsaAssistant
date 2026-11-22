"""Wires config, memory, LLM, connectors, tools, agent, voice, scheduler and the event bus."""
from __future__ import annotations

import asyncio
import logging
import platform
import threading
from typing import Any, Optional

from .brain.agent import Agent
from .brain.llm import OllamaLLM
from .brain.memory import Memory
from .config import Config, load_config
from .connectors.dashboard_browser import DashboardBrowser
from .connectors.discord_bot import DiscordConnector, DMsg
from .connectors.gmail_imap import GmailClient
from .connectors.whatsapp_client import WhatsAppClient

log = logging.getLogger("malice")


class Bus:
    """Fan-out of UI events (tokens, state, notifications) to every connected HUD."""

    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def publish_nowait(self, ev: dict) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    async def publish(self, ev: dict) -> None:
        self.publish_nowait(ev)


class Runtime:
    def __init__(self, cfg: Optional[Config] = None, llm: Any = None):
        import malice.tools  # noqa: F401  (registers tools)

        self.cfg = cfg or load_config()
        self.memory = Memory(self.cfg.db_path)
        self.llm = llm or OllamaLLM(self.cfg.llm)
        self.bus = Bus()
        self.gmail = GmailClient(self.cfg.gmail)
        self.dashboard = DashboardBrowser(self.cfg.dashboard)
        self.whatsapp = WhatsAppClient(self.cfg.whatsapp)
        self.discord = DiscordConnector(self.cfg.discord, on_owner_dm=self._discord_dm, on_alert=self._discord_alert)
        self.agent = Agent(self)
        self.voice = None  # VoiceLoop, created in start_voice()
        self.speak_replies = True
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ---------- conversation ----------
    async def ask(self, text: str, channel: str = "text") -> str:
        return await self.agent.respond(text, channel=channel, emit=self.bus.publish)

    async def ask_and_maybe_speak(self, text: str) -> str:
        reply = await self.ask(text, "text")
        if self.voice and self.speak_replies:
            threading.Thread(target=self.voice.say, args=(reply,), daemon=True).start()
        return reply

    async def _discord_dm(self, text: str) -> str:
        return await self.ask(text, channel="discord-dm")

    async def _discord_alert(self, m: DMsg) -> None:
        if self.memory.mark_seen("discord", str(m.id)):
            await self.notify(f"Discord #{m.channel}", f"{m.author}: {m.content[:180]}",
                              speak=f"{m.author} in {m.channel} on Discord: {m.content[:140]}" if m.mentions_me else None)

    # ---------- notifications ----------
    async def notify(self, title: str, body: str, speak: Optional[str] = None) -> None:
        await self.bus.publish({"type": "notify", "title": title, "body": body})
        await asyncio.to_thread(toast, title, body)
        if speak and self.voice and self.cfg.scheduler.speak_alerts and self.voice.state == "idle":
            threading.Thread(target=self.voice.say, args=(speak,), daemon=True).start()

    # ---------- lifecycle ----------
    async def start(self, voice: bool = True, scheduler: bool = True) -> dict:
        self.loop = asyncio.get_running_loop()
        status: dict[str, Any] = {}
        status["llm"] = await self.llm.health()
        await self.discord.start()
        if voice and self.cfg.voice.enabled:
            self.start_voice()
        status["voice"] = bool(self.voice)
        if scheduler and self.cfg.scheduler.enabled:
            from .scheduler import Scheduler
            self.scheduler = Scheduler(self)
            self.scheduler.start()
        return status

    def start_voice(self) -> None:
        from .voice.loop import VoiceLoop
        try:
            v = VoiceLoop(self, self.loop or asyncio.get_event_loop())
            v.start()
            self.voice = v
        except Exception as e:  # noqa: BLE001
            log.error("Voice disabled: %s", e)
            self.voice = None
            self.bus.publish_nowait({"type": "notify", "title": "Voice offline", "body": str(e)})

    async def stop(self) -> None:
        if self.voice:
            self.voice.stop()
        await self.discord.stop()
        await self.whatsapp.close()
        if hasattr(self.llm, "close"):
            await self.llm.close()

    async def connector_status(self) -> dict:
        out: dict[str, Any] = {}
        h = await self.llm.health()
        out["llm"] = {"ok": h.get("ok") and h.get("model_ready"), "detail": h.get("model") or h.get("error")}
        out["gmail"] = {"ok": self.gmail.configured, "detail": self.cfg.gmail.address or "not set"}
        out["dashboard"] = {"ok": self.dashboard.configured, "detail": self.cfg.dashboard.url or "not set"}
        if self.discord.configured:
            out["discord"] = {"ok": self.discord.ready.is_set() and not self.discord.error,
                              "detail": self.discord.error or ("connected" if self.discord.ready.is_set() else "connecting")}
        else:
            out["discord"] = {"ok": False, "detail": "no token"}
        try:
            st = await self.whatsapp.status()
            out["whatsapp"] = {"ok": st.get("connected"), "detail": "linked" if st.get("connected") else
                               ("scan QR" if st.get("hasQr") else "connecting")}
        except Exception:  # noqa: BLE001
            out["whatsapp"] = {"ok": False, "detail": "bridge not running"}
        out["voice"] = {"ok": bool(self.voice), "detail": (self.voice.stt.device if self.voice else "off")}
        return out


def toast(title: str, body: str) -> None:
    if platform.system() != "Windows":
        return
    try:
        from win11toast import toast as _toast  # type: ignore[import-not-found]
        _toast(title, body, app_id="M.A.L.I.C.E.", duration="short")
    except Exception:  # noqa: BLE001
        pass
