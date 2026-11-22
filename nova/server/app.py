"""HUD server: FastAPI + WebSocket on 127.0.0.1. Also the phone app, reached through Tailscale."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import config as config_mod
from ..brain.persona import GREETINGS
from ..config import inbox_dir
from .auth import COOKIE, LOGIN_HTML, SESSION_DAYS, Gate

log = logging.getLogger("nova.server")
STATIC = Path(__file__).parent / "static"
PUBLIC = ("/login", "/manifest.json", "/sw.js", "/static/")
MAX_UPLOAD = 25 * 1024 * 1024  # Discord's attachment limit
FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "tailscale-user-login")


def _forwarded(headers: Any) -> bool:
    return any(h in headers for h in FORWARD_HEADERS)


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def safe_filename(name: str) -> str:
    name = Path(name or "file").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[-80:] or "file"


def create_app(rt: Any, gate: Optional[Gate] = None) -> FastAPI:
    app = FastAPI(title="N.O.V.A.", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    gate = gate or Gate(rt.cfg.server)
    background: set[asyncio.Task] = set()

    def spawn(coro) -> None:  # noqa: ANN001
        t = asyncio.create_task(coro)
        background.add(t)
        t.add_done_callback(background.discard)

    @app.middleware("http")
    async def guard(request: Request, call_next):  # noqa: ANN001, ANN202
        path = request.url.path
        verdict = gate.check(request.headers.get("host", ""), request.cookies.get(COOKIE), _forwarded(request.headers))
        if verdict == "forbidden" and not (path.startswith("/static/") and gate.is_allowed_remote(request.headers.get("host", ""))):
            msg = "Remote access is off: set a PIN (NOVA_PIN in .env)." if not rt.cfg.server.pin else "Forbidden."
            return JSONResponse({"error": msg}, status_code=403)
        if verdict == "login" and not path.startswith(PUBLIC):
            if path.startswith("/api/"):
                return JSONResponse({"error": "login required"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    # ---------- login (phone) ----------
    @app.get("/login")
    async def login_page() -> HTMLResponse:
        return HTMLResponse(LOGIN_HTML.format(error=""))

    @app.post("/login")
    async def login(request: Request, pin: str = Form("")) -> Response:
        client = _client(request)
        if gate.locked(client):
            return HTMLResponse(LOGIN_HTML.format(error="Too many tries. Wait 15 minutes."), status_code=429)
        if not gate.try_pin(client, pin):
            return HTMLResponse(LOGIN_HTML.format(error="Wrong PIN."), status_code=401)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, gate.make_token(), max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=request.url.scheme == "https" or _forwarded(request.headers), samesite="strict")
        return resp

    # ---------- pages ----------
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/manifest.json")
    async def manifest() -> FileResponse:
        return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")

    @app.get("/sw.js")
    async def sw() -> FileResponse:
        return FileResponse(STATIC / "sw.js", media_type="text/javascript")

    # ---------- data ----------
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

    # ---------- phone: uploads, voice, spoken replies ----------
    async def _save(upload: UploadFile, folder: Path) -> Path:
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise ValueError("File is over 25 MB.")
        dest = folder / f"{int(time.time())}_{safe_filename(upload.filename or 'file')}"
        dest.write_bytes(data)
        return dest

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)) -> JSONResponse:
        try:
            dest = await _save(file, inbox_dir())
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=413)
        return JSONResponse({"name": dest.name, "size": dest.stat().st_size})

    @app.post("/api/voice")
    async def voice(audio: UploadFile = File(...), text: str = Form(""), attachments: str = Form("[]")) -> JSONResponse:
        folder = config_mod.DATA_DIR / "voice"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            path = await _save(audio, folder)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=413)
        files = _inbox_files(json.loads(attachments or "[]"))
        try:
            res = await rt.ask_remote(text, files, path, channel="phone")
        finally:
            path.unlink(missing_ok=True)
        audio_url = f"/api/tts/{res['audio'].name}" if res.get("audio") else None
        return JSONResponse({"transcript": res["transcript"], "reply": res["reply"], "audio_url": audio_url})

    @app.get("/api/tts/{name}")
    async def tts_file(name: str) -> Response:
        if not re.fullmatch(r"[0-9a-f]{32}\.wav", name):
            return JSONResponse({"error": "bad name"}, status_code=400)
        p = config_mod.DATA_DIR / "tts" / name
        if not p.exists():
            return JSONResponse({"error": "gone"}, status_code=404)
        return FileResponse(p, media_type="audio/wav")

    # ---------- live channel ----------
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        host = sock.headers.get("host", "")
        fwd = _forwarded(sock.headers)
        if gate.check(host, sock.cookies.get(COOKIE), fwd) != "ok":
            await sock.close(code=4401)
            return
        # Same-origin only: stops other websites open in a browser from driving the assistant.
        origin = urlparse(sock.headers.get("origin", "")).netloc
        if origin and origin != host and not gate.is_allowed_remote(origin):
            await sock.close(code=4403)
            return
        local = gate.is_local(host) and not fwd
        await sock.accept()
        q = rt.bus.subscribe()
        await sock.send_json({
            "type": "hello", "name": rt.cfg.assistant.name, "user": rt.cfg.assistant.user_name,
            "greeting": random.choice(GREETINGS).format(address=rt.cfg.assistant.address_as),
            "voice": bool(rt.voice), "speak": rt.speak_replies, "remote": not local,
            "pending": rt.agent._pending_view(),
        })

        async def pump() -> None:
            while True:
                await sock.send_json(await q.get())

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                msg = json.loads(await sock.receive_text())
                kind = msg.get("type")
                text = (msg.get("text") or "").strip()
                names = msg.get("attachments") or []
                if kind == "chat" and (text or names):
                    if local and not names:
                        spawn(rt.ask_and_maybe_speak(text))
                    else:  # phone: never talk out of the PC's speakers while he's out
                        spawn(rt.ask_remote(text, _inbox_files(names), None, channel="phone"))
                elif kind == "mic" and rt.voice and local:
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


def _inbox_files(names: list) -> list[Path]:
    root = inbox_dir().resolve()
    out = []
    for n in names if isinstance(names, list) else []:
        p = (root / Path(str(n)).name).resolve()
        if root in p.parents and p.exists():
            out.append(p)
    return out
