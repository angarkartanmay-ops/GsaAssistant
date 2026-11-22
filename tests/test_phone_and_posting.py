"""Round 2: phone access (gate, uploads, voice), posting as the user, attachments, undo."""
import io
import json
import wave
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from havoc.config import ServerCfg, WhatsAppCfg, inbox_dir
from havoc.connectors.whatsapp_client import WhatsAppClient
from havoc.server.auth import COOKIE, MAX_FAILS, Gate
from havoc.tools.common import AttachmentError, resolve_attachments

TS = "my-pc.tail1234.ts.net"


# ---------------------------------------------------------------- gate
def test_gate_rules(tmp_path):
    g = Gate(ServerCfg(pin="4321"), secret_file=tmp_path / "s")
    assert g.check("127.0.0.1:7777", None) == "ok"
    assert g.check("localhost:7777", None) == "ok"
    assert g.check(TS, None) == "login"
    assert g.check(TS, g.make_token()) == "ok"
    assert g.check(TS, "123.forged") == "login"
    assert g.check(TS, g.make_token(now=1)) == "login"  # issued in 1970, long expired
    assert g.check("evil.example.com", g.make_token()) == "forbidden"
    # A proxy that rewrites Host to localhost is still treated as remote.
    assert g.check("127.0.0.1:7777", None, forwarded=True) == "login"
    assert Gate(ServerCfg(pin=""), secret_file=tmp_path / "s2").check(TS, None) == "forbidden"


def test_pin_rate_limit(tmp_path):
    g = Gate(ServerCfg(pin="4321"), secret_file=tmp_path / "s")
    for _ in range(MAX_FAILS):
        assert not g.try_pin("phone", "0000")
    assert g.locked("phone")
    assert not g.try_pin("phone", "4321")  # even the right PIN is refused while locked
    assert g.try_pin("other-device", "4321")


# ---------------------------------------------------------------- server
def _wav_bytes(seconds=0.5, sr=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(sr * seconds)) / 8) * 8000).astype(np.int16).tobytes())
    return buf.getvalue()


@pytest.fixture
def phone(make_rt, tmp_path):
    from havoc.server.app import create_app
    rt = make_rt(["Posted, Sir."])
    rt.cfg.server.pin = "4321"
    app = create_app(rt, Gate(rt.cfg.server, secret_file=tmp_path / "secret"))
    return rt, TestClient(app, base_url=f"https://{TS}")


def test_pc_window_needs_no_pin(make_rt, tmp_path):
    from havoc.server.app import create_app
    rt = make_rt()
    c = TestClient(create_app(rt, Gate(rt.cfg.server, secret_file=tmp_path / "s")), base_url="http://127.0.0.1:7777")
    assert c.get("/").status_code == 200
    assert c.get("/api/tasks").status_code == 200


def test_phone_login_flow(phone):
    rt, c = phone
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/api/status").status_code == 401
    assert c.get("/manifest.json").status_code == 200  # installable before login
    assert c.post("/login", data={"pin": "9999"}).status_code == 401
    r = c.post("/login", data={"pin": "4321"}, follow_redirects=False)
    assert r.status_code == 303 and COOKIE in r.cookies
    assert c.get("/").status_code == 200
    assert c.get("/api/tasks").status_code == 200


def test_other_hosts_are_refused(phone):
    rt, c = phone
    r = c.get("/", headers={"host": "attacker.example"})
    assert r.status_code == 403


def test_remote_ws_requires_login(phone):
    from starlette.websockets import WebSocketDisconnect
    rt, c = phone
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()


def test_upload_and_voice(phone, monkeypatch):
    rt, c = phone
    c.post("/login", data={"pin": "4321"})
    r = c.post("/api/upload", files={"file": ("event photo.jpg", b"\xff\xd8fakejpeg", "image/jpeg")})
    assert r.status_code == 200
    name = r.json()["name"]
    assert (inbox_dir() / name).exists() and name.endswith("event_photo.jpg")

    heard = {}

    def fake_transcribe(path: Path) -> str:
        heard["bytes"] = path.read_bytes()[:4]
        return "post the photo to the GSA group"

    tts_dir = Path(rt.cfg.db_path).parent / "tts"

    def fake_speak(text: str) -> Path:
        tts_dir.mkdir(exist_ok=True)
        p = tts_dir / ("ab" * 16 + ".wav")
        p.write_bytes(_wav_bytes(0.1))
        return p

    monkeypatch.setattr(rt, "transcribe_file", fake_transcribe)
    monkeypatch.setattr(rt, "speak_to_file", fake_speak)
    import havoc.config as mc
    monkeypatch.setattr(mc, "DATA_DIR", Path(rt.cfg.db_path).parent)
    r = c.post("/api/voice", files={"audio": ("voice.webm", _wav_bytes(), "audio/webm")},
               data={"attachments": json.dumps([name])})
    body = r.json()
    assert r.status_code == 200, body
    assert heard["bytes"] == b"RIFF"
    assert body["transcript"] == "post the photo to the GSA group"
    assert body["reply"] == "Posted, Sir."
    assert body["audio_url"] == f"/api/tts/{'ab' * 16}.wav"
    assert c.get(body["audio_url"]).status_code == 200
    assert c.get("/api/tts/..%2Fsecret").status_code in (400, 404)
    # The model was told which files were attached.
    sent_to_llm = rt.llm.calls[-1]["messages"][-1]["content"]
    assert name in sent_to_llm and "Attached files" in sent_to_llm


# ---------------------------------------------------------------- attachments
def test_attachments_are_confined_to_inbox(cfg, tmp_path):
    f = inbox_dir() / "1763800000_slides.pdf"
    f.write_bytes(b"%PDF")
    assert resolve_attachments(["1763800000_slides.pdf"]) == [f.resolve()]
    assert resolve_attachments(["slides.pdf"]) == [f.resolve()]  # name without timestamp
    assert resolve_attachments("latest") == [f]
    secret = tmp_path / "passwords.txt"
    secret.write_text("x")
    with pytest.raises(AttachmentError):
        resolve_attachments([str(secret)])
    with pytest.raises(AttachmentError):
        resolve_attachments(["../passwords.txt"])  # path tricks only ever look inside the inbox


# ---------------------------------------------------------------- posting
@pytest.mark.asyncio
async def test_discord_and_whatsapp_post_directly_with_files_and_undo(make_rt):
    photo = inbox_dir() / "1763800000_photo.jpg"
    photo.write_bytes(b"jpg")
    calls = []

    async def dpost(channel, text, files=None):
        calls.append(("discord", channel, text, files))
        return f"Posted in #{channel} as Tanmay"

    async def wsend(group, text, files=None):
        calls.append(("wa", group, text, files))
        return "Sent to GSA."

    async def ddel():
        calls.append(("discord-undo",))
        return "Deleted my last Discord post."

    async def wdel():
        calls.append(("wa-undo",))
        return "Deleted my last WhatsApp message for everyone."

    rt = make_rt([{"tool": "wa_send", "args": {"message": "Workshop pics!", "attachments": ["photo.jpg"]}}, "Sent, Sir.",
                  {"tool": "discord_post", "args": {"channel": "general", "message": "Workshop recap"}}, "Posted, Sir.",
                  {"tool": "undo_last_post", "args": {}}, "Gone, Sir.",
                  {"tool": "undo_last_post", "args": {}}, "Also gone."])
    rt.discord.post, rt.whatsapp.send = dpost, wsend
    rt.discord.delete_last, rt.whatsapp.delete_last = ddel, wdel
    await rt.ask("send the workshop photo to the gsa whatsapp group")
    await rt.ask("post a workshop recap on discord")
    assert calls[0] == ("wa", None, "Workshop pics!", [photo.resolve()])
    assert calls[1][:3] == ("discord", "general", "Workshop recap")
    assert rt.agent.pending is None  # nothing waited for a yes
    await rt.ask("undo that")
    await rt.ask("undo the one before too")
    assert calls[2] == ("discord-undo",) and calls[3] == ("wa-undo",)


@pytest.mark.asyncio
async def test_discord_posts_via_webhook_as_user_and_falls_back(cfg, tmp_path):
    import discord

    from havoc.connectors.discord_bot import WEBHOOK_NAME, DiscordConnector

    f = inbox_dir() / "1763800000_poster.png"
    f.write_bytes(b"png")
    sent = []

    class Msg:
        jump_url = "https://discord.com/channels/1/2/3"
        channel = type("C", (), {"name": "general"})()

        async def delete(self):
            sent.append("deleted")

    class Hook:
        name = WEBHOOK_NAME
        user = type("U", (), {"id": 99})()

        async def send(self, content, username=None, avatar_url=None, files=None, wait=False):
            sent.append(("hook", content, username, avatar_url, [x.filename for x in files]))
            return Msg()

    class Chan:
        name = "general"
        allow = True

        async def webhooks(self):
            if not self.allow:
                raise discord.Forbidden(type("R", (), {"status": 403, "reason": "Forbidden"})(), "no perms")
            return [Hook()]

        async def send(self, content, files=None):
            sent.append(("bot", content))
            return Msg()

    cfg.discord.post_as_avatar = "https://cdn/avatar.png"
    dc = DiscordConnector(cfg.discord, default_name="Tanmay")
    dc.client = type("Client", (), {"user": type("U", (), {"id": 99})()})()
    ch = Chan()

    async def chan(name):
        return ch
    dc._channel = chan
    out = await dc.post("general", "Poster for Friday", [f])
    assert sent[0] == ("hook", "Poster for Friday", "Tanmay", "https://cdn/avatar.png", ["poster.png"])
    assert "as Tanmay" in out and "1 file" in out
    ch.allow = False
    out = await dc.post("general", "plain")
    assert sent[1] == ("bot", "plain") and "as the bot" in out
    assert await dc.delete_last() and sent[-1] == "deleted"


@pytest.mark.asyncio
async def test_whatsapp_client_sends_files_and_deletes():
    posts = []

    def handler(req):
        if req.url.path == "/status":
            return httpx.Response(200, json={"connected": True})
        if req.url.path == "/groups":
            return httpx.Response(200, json=[{"id": "1@g.us", "name": "GSA Batch"}])
        body = json.loads(req.content)
        posts.append((req.url.path, body))
        return httpx.Response(200, json={"ok": True, "id": f"m{len(posts)}"})

    c = WhatsAppClient(WhatsAppCfg(group_name="gsa"), transport=httpx.MockTransport(handler))
    out = await c.send(None, "Recap pics", [Path("/x/inbox/1_a.jpg"), Path("/x/inbox/2_b.jpg")])
    assert out == "Sent to GSA Batch with 2 files."
    assert posts[0] == ("/send", {"chat": "1@g.us", "text": "Recap pics", "file": "/x/inbox/1_a.jpg"})
    assert posts[1][1]["text"] == ""  # caption only on the first file
    await c.delete_last()
    assert posts[-1] == ("/delete", {"chat": "1@g.us", "id": "m2"})


def test_official_sender_and_attachment_names(cfg):
    from havoc.connectors.gmail_imap import GmailClient
    cfg.gmail.address, cfg.gmail.app_password = "me@gmail.com", "abcd"
    g = GmailClient(cfg.gmail)
    assert g.sender.address == "me@gmail.com"
    cfg.gmail.official_address, cfg.gmail.official_app_password = "tanmay@college.edu", "wxyz"
    cfg.gmail.sender_name = "Tanmay A"
    assert g.sender.address == "tanmay@college.edu" and g.reader.address == "me@gmail.com"
    f = inbox_dir() / "1763800000_report.pdf"
    f.write_bytes(b"%PDF-1.4")
    msg = g.build_new("poc@google.com", "October report", "Attached.", [f])
    assert msg["From"] == "Tanmay A <tanmay@college.edu>"
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["report.pdf"]
    cfg.gmail.official_app_password, cfg.gmail.official_auth = "", "oauth"
    assert g.can_send  # oauth needs no stored password


@pytest.mark.asyncio
async def test_unanswerable_phone_turn(make_rt):
    rt = make_rt()
    res = await rt.ask_remote("", [], None)
    assert "Sir" in res["reply"]
