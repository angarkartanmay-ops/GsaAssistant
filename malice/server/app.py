"""Local HUD: FastAPI + WebSocket on 127.0.0.1."""
from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..brain.persona import GREETINGS

log = logging.getLogger("malice.server")
STATIC = Path(__file__).parent / "static"


def create_app(rt: Any) -> FastAPI:
    app = FastAPI(title="M.A.L.I.C.E.", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    background: set[asyncio.Task] = set()

    def spawn(coro) -> None:  # noqa: ANN001
        t = asyncio.create_task(coro)
        background.add(t)
        t.add_done_callback(background.discard)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    async def status() -> JSONResponse:
        return JSONResponse({"name": rt.cfg.assistant.name, "user": rt.cfg.assistant.user_name,
                             "connectors": await rt.connector_status()})

    @app.get("/api/tasks")
    async def tasks() -> JSONResponse:
        return JSONResponse([t.__dict__ for t in rt.memory.tasks()])

    @app.get("/api/whatsapp/qr")
    async def wa_qr() -> JSONResponse:
        try:
            return JSONResponse(await rt.whatsapp.qr())
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=503)

    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        # Only the local HUD may connect; blocks other sites from driving the assistant.
        origin = sock.headers.get("origin", "")
        port = rt.cfg.server.port
        allowed = {f"{rt.cfg.server.host}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"}
        if origin and urlparse(origin).netloc not in allowed:
            await sock.close(code=4403)
            return
        await sock.accept()
        q = rt.bus.subscribe()
        await sock.send_json({
            "type": "hello", "name": rt.cfg.assistant.name, "user": rt.cfg.assistant.user_name,
            "greeting": random.choice(GREETINGS).format(address=rt.cfg.assistant.address_as),
            "voice": bool(rt.voice), "speak": rt.speak_replies,
            "pending": rt.agent._pending_view(),
        })

        async def pump() -> None:
            while True:
                ev = await q.get()
                await sock.send_json(ev)

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                msg = json.loads(await sock.receive_text())
                kind = msg.get("type")
                if kind == "chat" and msg.get("text", "").strip():
                    spawn(rt.ask_and_maybe_speak(msg["text"].strip()))
                elif kind == "mic" and rt.voice:
                    rt.voice.trigger()
                elif kind == "stop" and rt.voice:
                    rt.voice.tts.stop()
                elif kind == "speak":
                    rt.speak_replies = bool(msg.get("on"))
                elif kind == "mute" and rt.voice:
                    rt.voice.muted = bool(msg.get("on"))
                elif kind == "reset":
                    rt.agent.reset()
                    await sock.send_json({"type": "notify", "title": "Memory", "body": "Conversation cleared."})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump_task.cancel()
            rt.bus.unsubscribe(q)

    return app
