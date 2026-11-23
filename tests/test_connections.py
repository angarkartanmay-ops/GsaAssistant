"""Round 4: Connections (settings), PC-only gating, shared history, restart."""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from havoc.server.auth import Gate

TS = "my-pc.tail1234.ts.net"


@pytest.fixture
def home(tmp_path, monkeypatch):
    import havoc.config as mc
    monkeypatch.setattr(mc, "HOME", tmp_path)
    monkeypatch.setattr(mc, "DATA_DIR", tmp_path / "data")
    return tmp_path


@pytest.fixture
def clients(make_rt, home, tmp_path):
    from havoc.server.app import create_app
    rt = make_rt(["Done, Sir."])
    rt.cfg.server.pin = "4321"
    restarted = []
    app = create_app(rt, Gate(rt.cfg.server, secret_file=tmp_path / "secret"), on_restart=lambda: restarted.append(1))
    pc = TestClient(app, base_url="http://127.0.0.1:7777")
    phone = TestClient(app, base_url=f"https://{TS}")
    phone.post("/login", data={"pin": "4321"})
    return rt, pc, phone, restarted


def test_settings_roundtrip_never_returns_secrets(clients, home):
    rt, pc, phone, _ = clients
    r = pc.post("/api/settings", json={
        "fields": {"gmail.address": "me@gmail.com", "discord.guild_id": "123456789012345678", "assistant.sass": 2},
        "secrets": {"gmail.app_password": "abcd efgh ijkl mnop", "discord.token": "tok.en.value", "server.pin": "9876"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["restart_needed"]
    env = (home / ".env").read_text()
    assert "GMAIL_APP_PASSWORD=abcdefghijklmnop" in env  # spaces stripped
    assert "DISCORD_BOT_TOKEN=tok.en.value" in env and "HAVOC_PIN=9876" in env
    assert "WA_BRIDGE_TOKEN=" in env
    import yaml
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["discord"]["guild_id"] == 123456789012345678 and cfg["assistant"]["sass"] == 2

    view = pc.get("/api/settings").json()
    assert view["secrets"] == {"gmail.app_password": True, "gmail.official_app_password": False,
                               "discord.token": True, "server.pin": True}
    assert view["fields"]["gmail.address"] == "me@gmail.com"
    body = pc.get("/api/settings").text
    for secret in ("abcdefghijklmnop", "tok.en.value", "9876"):
        assert secret not in body

    # Clearing a secret removes it from .env.
    pc.post("/api/settings", json={"secrets": {"discord.token": None}})
    assert "DISCORD_BOT_TOKEN" not in (home / ".env").read_text()


def test_settings_validation(clients):
    _, pc, _, _ = clients
    assert pc.post("/api/settings", json={"fields": {"discord.guild_id": "abc"}}).status_code == 400
    assert pc.post("/api/settings", json={"fields": {"assistant.sass": 7}}).status_code == 400
    assert pc.post("/api/settings", json={"secrets": {"server.pin": "12"}}).status_code == 400
    assert pc.post("/api/settings", json={"fields": {"made.up": "x"}}).status_code == 400
    assert pc.post("/api/settings", json={"fields": {"gmail.address": "not-an-email"}}).status_code == 400


def test_connections_from_the_unlocked_phone(clients, home, tmp_path):
    from fastapi.testclient import TestClient
    rt, pc, phone, _ = clients
    # The PIN-unlocked phone can connect accounts...
    r = phone.post("/api/settings", json={"secrets": {"discord.token": "from.the.phone"}})
    assert r.status_code == 200, r.text
    assert "DISCORD_BOT_TOKEN=from.the.phone" in (home / ".env").read_text()
    # ...but secrets still never come back out.
    assert "from.the.phone" not in phone.get("/api/settings").text
    assert phone.get("/api/me").json()["local"] is False
    # A phone without the PIN gets nothing.
    stranger = TestClient(phone.app, base_url=f"https://{TS}")
    assert stranger.get("/api/settings").status_code == 401
    assert stranger.post("/api/settings", json={"secrets": {"server.pin": "0000"}}).status_code == 401


def test_app_download_page_is_reachable_before_login(clients, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import havoc.server.app as server_app
    apk = tmp_path / "HAVOC.apk"
    apk.write_bytes(b"PK\x03\x04fake")
    monkeypatch.setattr(server_app, "APK", apk)
    _, _, phone, _ = clients
    fresh = TestClient(phone.app, base_url=f"https://{TS}")
    page = fresh.get("/app")
    assert page.status_code == 200 and f"https://{TS}" in page.text and "/app/havoc.apk" in page.text
    r = fresh.get("/app/havoc.apk")
    assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.android.package-archive"
    assert fresh.get("/app", headers={"host": "evil.example"}).status_code == 403


def test_restart_from_pc(clients):
    import time
    _, pc, _, restarted = clients
    with pc:  # keeps the app's event loop running so the scheduled restart can fire
        assert pc.post("/api/restart").json() == {"ok": True}
        time.sleep(0.8)
    assert restarted == [1]


def test_shared_history_across_devices(clients):
    rt, pc, phone, _ = clients
    with pc.websocket_connect("/ws", headers={"host": "127.0.0.1:7777"}) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["history"] == [] and hello["state"] == "idle"
        ws.send_json({"type": "chat", "text": "how are you holding up?"})
        seen = []
        while True:
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] == "final":
                break
        assert "user" in seen  # every screen gets the user's turn, not just the sender
    # The phone, connecting afterwards, gets the whole exchange.
    # The test client sends neither the Secure cookie nor the real Host on its websocket; browsers do.
    cookie = f"havoc_session={phone.cookies.get('havoc_session')}"
    with phone.websocket_connect("/ws", headers={"host": TS, "origin": f"https://{TS}", "cookie": cookie}) as ws:
        hello = ws.receive_json()
        assert [h["role"] for h in hello["history"]] == ["user", "assistant"]
        assert hello["history"][0]["content"] == "how are you holding up?"
        assert hello["remote"] is True
    assert phone.get("/api/history").json()[-1]["content"] == "Done, Sir."


def test_discord_invite_url_from_token():
    from havoc.server.app import discord_invite_url
    app_id = "123456789012345678"
    token = base64.b64encode(app_id.encode()).decode().rstrip("=") + ".abc.def"
    url = discord_invite_url(token)
    assert url == f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot&permissions=536939520"
    assert discord_invite_url("garbage") is None


def test_havoc_home_moves_user_files(tmp_path, monkeypatch):
    import importlib

    import havoc.config as mc
    monkeypatch.setenv("HAVOC_HOME", str(tmp_path / "home"))
    importlib.reload(mc)
    try:
        assert mc.config_path() == (tmp_path / "home" / "config.yaml").resolve()
        assert mc.DATA_DIR == (tmp_path / "home" / "data").resolve()
        cfg = mc.load_config()
        assert Path(cfg.dashboard.profile_dir).is_relative_to(tmp_path / "home")
        assert (tmp_path / "home" / "knowledge" / "gsa.md").exists()  # copied on first run
    finally:
        monkeypatch.delenv("HAVOC_HOME")
        importlib.reload(mc)
