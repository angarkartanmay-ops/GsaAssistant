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
from ..config import ROOT, inbox_dir
from .auth import COOKIE, LOGIN_HTML, SESSION_DAYS, Gate

log = logging.getLogger("havoc.server")
STATIC = Path(__file__).parent / "static"
# Reachable before the PIN (still only via localhost or your own Tailscale): the login page, the
# app manifest/icons, and the phone app download, which you need before you can log in.
PUBLIC = ("/login", "/manifest.json", "/sw.js", "/static/", "/app")
APK = ROOT / "releases" / "HAVOC.apk"
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


def discord_invite_url(token: str) -> Optional[str]:
    """A bot token's first segment is the bot's user id (= application id), base64-encoded."""
    import base64
    try:
        seg = token.split(".")[0]
        app_id = base64.b64decode(seg + "=" * (-len(seg) % 4)).decode()
    except Exception:  # noqa: BLE001
        return None
    if not app_id.isdigit():
        return None
    return f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot&permissions=536939520"


def create_app(rt: Any, gate: Optional[Gate] = None, on_restart: Optional[Any] = None) -> FastAPI:
    app = FastAPI(title="H.A.V.O.C.", docs_url=None, redoc_url=None, openapi_url=None)
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
            msg = "Remote access is off: set a PIN (HAVOC_PIN in .env)." if not rt.cfg.server.pin else "Forbidden."
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
    def is_local_request(request: Request) -> bool:
        return gate.is_local(request.headers.get("host", "")) and not _forwarded(request.headers)

    def pc_only(request: Request) -> Optional[JSONResponse]:
        # Connections work from the PC and from your PIN-unlocked phone (the guard middleware has
        # already rejected anything else). Secrets stay write-only: they're never sent back out.
        return None

    @app.get("/")
    async def index() -> FileResponse:
        app_index = STATIC / "app" / "index.html"
        return FileResponse(app_index if app_index.exists() else STATIC / "index.html")

    @app.get("/app")
    async def app_page(request: Request) -> HTMLResponse:
        host = request.headers.get("host", "")
        address = f"https://{host}" if gate.is_allowed_remote(host) else (
            f"https://{rt.cfg.server.remote_hosts[0]}" if rt.cfg.server.remote_hosts else "")
        ready = APK.exists()
        return HTMLResponse(APP_PAGE.format(
            address=address or "(set up phone access in Connections first)",
            size=f"{APK.stat().st_size / 2**20:.0f} MB" if ready else "",
            download='<a class="btn" href="/app/havoc.apk">Download HAVOC.apk</a>' if ready
            else '<p class="err">The APK isn\'t on this PC yet. Run <code>git pull</code> in the HAVOC folder.</p>'))

    @app.get("/app/havoc.apk")
    async def app_apk() -> Response:
        if not APK.exists():
            return JSONResponse({"error": "APK not found; git pull in the HAVOC folder"}, status_code=404)
        return FileResponse(APK, media_type="application/vnd.android.package-archive", filename="HAVOC.apk")

    @app.get("/classic")
    async def classic() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/me")
    async def me(request: Request) -> JSONResponse:
        return JSONResponse({"name": rt.cfg.assistant.name, "spoken": rt.cfg.assistant.spoken_name,
                             "user": rt.cfg.assistant.user_name, "address": rt.cfg.assistant.address_as,
                             "local": is_local_request(request), "voice": bool(rt.voice)})

    @app.get("/api/history")
    async def history(limit: int = 40) -> JSONResponse:
        return JSONResponse(rt.memory.history(max(1, min(limit, 200))))

    # ---------- connections (PC only: secrets never leave this machine) ----------
    @app.get("/api/settings")
    async def get_settings(request: Request) -> JSONResponse:
        if (deny := pc_only(request)):
            return deny
        from ..settings import read_env, view
        data = view(rt.cfg)
        token = read_env().get("DISCORD_BOT_TOKEN", "")
        data["discord_invite_url"] = discord_invite_url(token) if token else None
        data["phone_url"] = f"https://{rt.cfg.server.remote_hosts[0]}" if rt.cfg.server.remote_hosts else None
        return JSONResponse(data)

    @app.post("/api/settings")
    async def post_settings(request: Request) -> JSONResponse:
        if (deny := pc_only(request)):
            return deny
        from ..settings import SettingsError, apply
        try:
            changed = apply(await request.json())
        except (SettingsError, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"changed": changed, "restart_needed": bool(changed)})

    @app.post("/api/restart")
    async def restart(request: Request) -> JSONResponse:
        if (deny := pc_only(request)):
            return deny
        if on_restart is None:
            return JSONResponse({"error": "Restart isn't available in this mode."}, status_code=400)
        asyncio.get_running_loop().call_later(0.5, on_restart)
        return JSONResponse({"ok": True})

    @app.post("/api/connect/{what}")
    async def connect(what: str, request: Request) -> JSONResponse:
        """Starts a sign-in that needs a browser on the PC (dashboard Google login, mail OAuth)."""
        if (deny := pc_only(request)):
            return deny
        if what == "dashboard":
            if not rt.cfg.dashboard.url:
                return JSONResponse({"error": "Save the dashboard URL first."}, status_code=400)
            spawn(_run_login(rt, "dashboard", rt.dashboard.login()))
        elif what == "mail":
            from ..connectors.google_oauth import access_token
            targets = [a for a, auth in ((rt.cfg.gmail.address, rt.cfg.gmail.auth),
                                         (rt.cfg.gmail.official_address, rt.cfg.gmail.official_auth))
                       if a and auth == "oauth"]
            if not targets:
                return JSONResponse({"error": "No mail account is set to Google sign-in."}, status_code=400)
            for addr in targets:
                spawn(_run_login(rt, f"mail {addr}", asyncio.to_thread(
                    access_token, addr, rt.cfg.gmail.oauth_client_file, True)))
        elif what == "phone":
            spawn(_enable_phone(rt))
            return JSONResponse({"ok": True, "message": "Setting up phone access. If Tailscale asks you to sign in, a browser window opens."})
        else:
            return JSONResponse({"error": f"Nothing to connect called {what}."}, status_code=404)
        return JSONResponse({"ok": True, "message": "A sign-in window is opening on the PC."})

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
            # The shared brain: whatever device you open, you see the same conversation.
            "history": rt.memory.history(40),
            "state": "thinking" if rt.agent.lock.locked() else (rt.voice.state if rt.voice else "idle"),
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


APP_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>HAVOC for Android</title>
<style>
:root{{--bg:#0c0d10;--panel:#121419;--text:#e8eaef;--muted:#8a909c;--accent:#5cb4d9;--bad:#e06a70}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100dvh;background:var(--bg);color:var(--text);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:28px 18px}}
main{{max-width:460px;margin:0 auto;display:flex;flex-direction:column;gap:18px}}
.brand{{font:600 15px ui-monospace,Consolas,monospace;letter-spacing:.34em}}
h1{{font-size:24px;margin:0;letter-spacing:-.01em}}p{{margin:0;color:var(--muted)}}
ol{{margin:0;padding-left:20px;color:var(--muted)}}li{{margin:6px 0}}b{{color:var(--text)}}
.btn{{display:block;text-align:center;padding:15px;border-radius:14px;background:var(--accent);color:var(--bg);
font-weight:700;text-decoration:none}}button{{padding:12px;border-radius:12px;border:1px solid rgba(255,255,255,.1);
background:var(--panel);color:var(--text);font:inherit;width:100%}}code{{font-family:ui-monospace,monospace;color:var(--text)}}
.addr{{background:var(--panel);border-radius:12px;padding:12px 14px;font:14px ui-monospace,monospace;word-break:break-all}}
.err{{color:var(--bad)}}
</style></head><body><main>
<div class="brand">H.A.V.O.C.</div>
<h1>Phone app</h1>
<p>Same brain, same conversation as your PC, plus "Hey Havoc". {size}</p>
{download}
<div><p style="margin-bottom:6px">Your PC's address (the app fills it in if you copy it first):</p>
<div class="addr" id="addr">{address}</div></div>
<button onclick="navigator.clipboard.writeText(document.getElementById('addr').textContent.trim()).then(()=>this.textContent='Copied')">Copy address</button>
<ol>
<li>Tap <b>Copy address</b>, then <b>Download</b>.</li>
<li>Open the file. If asked, allow your browser to <b>install unknown apps</b> (just this once).</li>
<li>Open HAVOC, check the address, enter your <b>PIN</b>, tap Connect.</li>
<li>Allow the microphone and notifications. Turn on <b>Hey Havoc</b> under Today.</li>
</ol>
<p>Updating later: download again and install over the top. Your settings stay.</p>
</main></body></html>"""


async def _enable_phone(rt: Any) -> None:
    from ..settings import apply
    from ..tailscale import enable_phone_access
    notes: list[str] = []
    try:
        name = await asyncio.to_thread(enable_phone_access, rt.cfg.server.port, notes.append)
        if name:
            apply({"fields": {"server.remote_hosts": [name]}})
            rt.cfg.server.remote_hosts = [name]
    except Exception as e:  # noqa: BLE001
        notes.append(f"Phone setup failed: {e}")
    await rt.bus.publish({"type": "notify", "title": "Phone access", "body": " ".join(notes) or "Done."})


async def _run_login(rt: Any, label: str, coro) -> None:  # noqa: ANN001
    try:
        await coro
        await rt.bus.publish({"type": "notify", "title": "Connected", "body": f"{label} sign-in saved."})
    except Exception as e:  # noqa: BLE001
        await rt.bus.publish({"type": "notify", "title": "Sign-in failed", "body": f"{label}: {e}"})


def _inbox_files(names: list) -> list[Path]:
    root = inbox_dir().resolve()
    out = []
    for n in names if isinstance(names, list) else []:
        p = (root / Path(str(n)).name).resolve()
        if root in p.parents and p.exists():
            out.append(p)
    return out
