"""Background jobs: new GSA mail, dashboard changes, WhatsApp alerts, reminders, morning briefing."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from .tools.common import blocking

log = logging.getLogger("havoc.scheduler")


class Scheduler:
    def __init__(self, rt: Any):
        self.rt = rt
        self.cfg = rt.cfg
        self.tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self._every(30, self.check_reminders)),
            asyncio.create_task(self._every(self.cfg.scheduler.poll_minutes * 60, self.check_mail, delay=20)),
            asyncio.create_task(self._every(120, self.check_whatsapp, delay=40)),
            asyncio.create_task(self._every(self.cfg.dashboard.refresh_minutes * 60, self.check_dashboard, delay=90)),
            asyncio.create_task(self._every(30, self.check_briefing)),
        ]

    async def _every(self, seconds: float, fn, delay: float = 0) -> None:  # noqa: ANN001
        await asyncio.sleep(delay)
        while True:
            try:
                await fn()
            except Exception as e:  # noqa: BLE001
                log.debug("%s failed: %s", fn.__name__, e)
            await asyncio.sleep(seconds)

    async def check_reminders(self) -> None:
        for rid, _ts, text in self.rt.memory.due_reminders():
            self.rt.memory.finish_reminder(rid)
            await self.rt.notify("Reminder", text, speak=f"{self.cfg.assistant.address_as}, a reminder: {text}")

    async def check_mail(self) -> None:
        if not self.rt.gmail.configured:
            return
        mails = await blocking(self.rt.gmail.gsa_mails, 2, True, 15)
        fresh = [m for m in mails if self.rt.memory.mark_seen("gmail", m.msgid)]
        if not fresh:
            return
        if len(fresh) == 1:
            m = fresh[0]
            sender = m.sender.split("<")[0].strip().strip('"') or m.sender
            await self.rt.notify("New GSA mail", f"{sender}: {m.subject}", speak=f"New program mail from {sender}: {m.subject}.")
        else:
            subjects = "; ".join(m.subject for m in fresh[:4])
            await self.rt.notify(f"{len(fresh)} new GSA mails", subjects,
                                 speak=f"{len(fresh)} new program mails. Say 'brief me' when you want them.")

    async def check_whatsapp(self) -> None:
        if not self.rt.whatsapp.configured:
            return
        since = self.rt.memory.get("wa_alert_since", time.time() - 600)
        try:
            group = await self.rt.whatsapp.find_group()
        except Exception:  # noqa: BLE001
            return
        msgs = await self.rt.whatsapp.all_new(since)
        self.rt.memory.set("wa_alert_since", time.time())
        user = self.cfg.assistant.user_name.lower()
        for m in msgs:
            if m.chat != group["id"] or m.from_me:
                continue
            low = m.text.lower()
            if user in low or any(k in low for k in self.cfg.whatsapp.alert_keywords):
                if self.rt.memory.mark_seen("whatsapp", m.id):
                    await self.rt.notify(f"WhatsApp · {group['name']}", f"{m.sender}: {m.text[:180]}",
                                         speak=f"{m.sender} in the GSA group: {m.text[:140]}" if user in low else None)

    async def check_dashboard(self) -> None:
        if not self.rt.dashboard.configured:
            return
        from .tools.dashboard import sync_dashboard
        res = await sync_dashboard(self.rt)
        if res["new"] and self.rt.memory.get("dashboard_initialised", False):
            await self.rt.notify("New dashboard task", "; ".join(res["new"][:5]),
                                 speak=f"The dashboard has {len(res['new'])} new task(s). The first: {res['new'][0]}.")
        self.rt.memory.set("dashboard_initialised", True)

    async def check_briefing(self) -> None:
        hhmm = self.cfg.scheduler.briefing_time
        today = datetime.now().strftime("%Y-%m-%d")
        if not hhmm or datetime.now().strftime("%H:%M") < hhmm or self.rt.memory.get("briefed_on") == today:
            return
        self.rt.memory.set("briefed_on", today)
        if datetime.now().hour >= 13:
            return  # PC turned on late: no "morning" briefing at 9pm. Ask for one any time instead.
        reply =await self.rt.ask("Give me my morning GSA briefing.", channel="voice" if self.rt.voice else "text")
        await self.rt.notify("Morning briefing", reply[:250])
        if self.rt.voice:
            await asyncio.to_thread(self.rt.voice.say, reply)
