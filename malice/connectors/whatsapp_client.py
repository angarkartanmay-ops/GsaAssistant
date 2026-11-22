"""Python side of the WhatsApp bridge (whatsapp-bridge/index.js on 127.0.0.1)."""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from ..config import WhatsAppCfg


@dataclass
class WAMsg:
    id: str
    chat: str
    chat_name: str
    sender: str
    text: str
    ts: float
    from_me: bool

    def line(self) -> str:
        t = datetime.fromtimestamp(self.ts).strftime("%d %b %H:%M")
        who = "You" if self.from_me else self.sender
        return f"[{t}] {who}: {self.text}"


class WhatsAppError(RuntimeError):
    pass


class WhatsAppClient:
    def __init__(self, cfg: WhatsAppCfg, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.cfg = cfg
        headers = {"x-bridge-token": cfg.bridge_token} if cfg.bridge_token else {}
        self._http = httpx.AsyncClient(base_url=cfg.bridge_url, headers=headers, timeout=20,
                                       transport=transport)

    @property
    def configured(self) -> bool:
        return self.cfg.enabled

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params) -> object:
        try:
            r = await self._http.get(path, params=params)
        except httpx.HTTPError as e:
            raise WhatsAppError("The WhatsApp bridge isn't running. Start it with start.bat "
                                "(or `npm start` in whatsapp-bridge).") from e
        if r.status_code == 401:
            raise WhatsAppError("Bridge token mismatch: WA_BRIDGE_TOKEN must match in .env.")
        r.raise_for_status()
        return r.json()

    async def status(self) -> dict:
        return await self._get("/status")  # type: ignore[return-value]

    async def qr(self) -> dict:
        return await self._get("/qr")  # type: ignore[return-value]

    async def groups(self) -> list[dict]:
        st = await self.status()
        if not st.get("connected"):
            raise WhatsAppError("WhatsApp isn't linked yet. Open the HUD (or the bridge window) "
                                "and scan the QR code in WhatsApp > Linked devices.")
        return await self._get("/groups")  # type: ignore[return-value]

    async def find_group(self, name: Optional[str] = None) -> dict:
        name = (name or self.cfg.group_name).strip().lower()
        groups = await self.groups()
        if not groups:
            raise WhatsAppError("No WhatsApp groups found on this account yet.")
        exact = [g for g in groups if g["name"] and g["name"].lower() == name]
        if exact:
            return exact[0]
        contains = [g for g in groups if g["name"] and name in g["name"].lower()]
        if contains:
            return contains[0]
        names = {g["name"].lower(): g for g in groups if g["name"]}
        close = difflib.get_close_matches(name, list(names), n=1, cutoff=0.5)
        if close:
            return names[close[0]]
        raise WhatsAppError(f"No group like '{name}'. Groups: {', '.join(g['name'] for g in groups[:25])}")

    async def messages(self, group: Optional[str] = None, hours: float = 24, limit: int = 300) -> tuple[dict, list[WAMsg]]:
        g = await self.find_group(group)
        since = int(time.time() - hours * 3600)
        rows = await self._get("/messages", chat=g["id"], since=since, limit=limit)
        msgs = [WAMsg(r["id"], r["chat"], r.get("chatName", ""), r["sender"], r["text"], float(r["ts"]),
                      bool(r.get("fromMe"))) for r in rows]  # type: ignore[union-attr]
        return g, msgs

    async def all_new(self, since: float) -> list[WAMsg]:
        rows = await self._get("/messages", since=int(since), limit=500)
        return [WAMsg(r["id"], r["chat"], r.get("chatName", ""), r["sender"], r["text"], float(r["ts"]),
                      bool(r.get("fromMe"))) for r in rows]  # type: ignore[union-attr]

    async def send(self, group: Optional[str], text: str) -> str:
        g = await self.find_group(group)
        try:
            r = await self._http.post("/send", json={"chat": g["id"], "text": text})
        except httpx.HTTPError as e:
            raise WhatsAppError("The WhatsApp bridge isn't running.") from e
        if r.status_code >= 400:
            raise WhatsAppError(f"Send failed: {r.json().get('error', r.text)}")
        return f"Sent to {g['name']}."
