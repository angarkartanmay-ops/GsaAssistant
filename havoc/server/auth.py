"""Access control for the HUD.

* Requests addressed to localhost / 127.0.0.1 (the PC's own app window) are trusted.
* Requests arriving through Tailscale (`tailscale serve` -> https://<pc>.<tailnet>.ts.net) must
  carry a signed session cookie, obtained by typing the PIN on /login. Tailscale already keeps
  the page off the public internet; the PIN covers a lost or borrowed phone.
* Any other Host is refused, which also blocks DNS-rebinding tricks from random websites.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

from .. import config as config_mod
from ..config import ServerCfg

COOKIE = "havoc_session"
SESSION_DAYS = 30
MAX_FAILS = 5
FAIL_WINDOW_S = 15 * 60
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _host_only(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.split(":")[0]


class Gate:
    def __init__(self, cfg: ServerCfg, secret_file: Optional[Path] = None):
        self.cfg = cfg
        self.secret_file = secret_file or (config_mod.DATA_DIR / "session_secret")
        self._secret: Optional[bytes] = None
        self.fails: dict[str, deque] = defaultdict(deque)

    @property
    def secret(self) -> bytes:
        if self._secret is None:
            if self.secret_file.exists():
                self._secret = self.secret_file.read_bytes()
            else:
                self._secret = secrets.token_bytes(32)
                self.secret_file.parent.mkdir(parents=True, exist_ok=True)
                self.secret_file.write_bytes(self._secret)
        return self._secret

    # ----- classification -----
    def is_local(self, host: str) -> bool:
        return _host_only(host) in LOCAL_HOSTS

    def is_allowed_remote(self, host: str) -> bool:
        h = _host_only(host)
        if self.cfg.remote_hosts:
            return h in {x.lower() for x in self.cfg.remote_hosts}
        return h.endswith(".ts.net")

    # ----- sessions -----
    def make_token(self, now: Optional[float] = None) -> str:
        exp = int((time.time() if now is None else now) + SESSION_DAYS * 86400)
        sig = hmac.new(self.secret, str(exp).encode(), hashlib.sha256).hexdigest()
        return f"{exp}.{sig}"

    def valid_token(self, token: Optional[str], now: Optional[float] = None) -> bool:
        if not token or "." not in token:
            return False
        exp, sig = token.split(".", 1)
        if not exp.isdigit() or int(exp) < (time.time() if now is None else now):
            return False
        good = hmac.new(self.secret, exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good)

    def check(self, host: str, cookie: Optional[str], forwarded: bool = False) -> str:
        """Returns 'ok', 'login' (needs PIN) or 'forbidden'.

        `forwarded` = the request carries proxy headers (X-Forwarded-*, Tailscale-User-*). The PC's
        own window never sends those, so a proxied request is treated as remote even if the proxy
        rewrote Host to 127.0.0.1."""
        if self.is_local(host) and not forwarded:
            return "ok"
        if not (self.is_allowed_remote(host) or self.is_local(host)) or not self.cfg.pin:
            return "forbidden"
        return "ok" if self.valid_token(cookie) else "login"

    # ----- PIN attempts -----
    def locked(self, client: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        q = self.fails[client]
        while q and now - q[0] > FAIL_WINDOW_S:
            q.popleft()
        return len(q) >= MAX_FAILS

    def try_pin(self, client: str, pin: str, now: Optional[float] = None) -> bool:
        if not self.cfg.pin or self.locked(client, now):
            return False
        if hmac.compare_digest(pin.strip().encode(), self.cfg.pin.encode()):
            self.fails.pop(client, None)
            return True
        self.fails[client].append(time.time() if now is None else now)
        return False


LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>H.A.V.O.C.</title>
<link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0b0d12">
<style>
:root{{--bg:#0b0d12;--text:#e8ecf3;--muted:#8a93a6;--accent:#4fd1ff;--err:#ff6b6b}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px}}
form{{width:100%;max-width:340px;display:flex;flex-direction:column;gap:14px;text-align:center}}
h1{{font:700 20px/1 ui-monospace,Consolas,monospace;letter-spacing:.35em;color:var(--accent);margin:0 0 4px}}
p{{color:var(--muted);margin:0}}input{{font:600 24px ui-monospace,monospace;letter-spacing:.4em;text-align:center;
padding:14px;border-radius:12px;border:1px solid #2a3040;background:#121621;color:var(--text);outline:none}}
input:focus{{border-color:var(--accent)}}button{{padding:14px;border:0;border-radius:12px;background:var(--accent);
color:#04131a;font:700 16px system-ui}}.err{{color:var(--err);min-height:1.5em}}
</style></head><body><form method="post" action="/login">
<h1>H.A.V.O.C.</h1><p>Enter your PIN, Sir.</p>
<input name="pin" type="password" inputmode="numeric" autocomplete="current-password" autofocus required>
<button type="submit">Unlock</button><div class="err">{error}</div></form></body></html>"""
