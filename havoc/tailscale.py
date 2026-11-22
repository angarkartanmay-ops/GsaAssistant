"""Tailscale helpers: the private link that lets your phone reach HAVOC on this PC.

`tailscale serve --bg 7777` publishes the HUD at https://<pc>.<tailnet>.ts.net, visible only to
devices signed in to your own Tailscale account. HAVOC itself keeps listening on 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from typing import Callable

WINDOWS_EXE = r"C:\Program Files\Tailscale\tailscale.exe"


def exe() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    if platform.system() == "Windows" and os.path.exists(WINDOWS_EXE):
        return WINDOWS_EXE
    return ""


def host() -> str:
    """This PC's Tailscale name, e.g. my-pc.tail1234.ts.net ('' if Tailscale isn't up)."""
    ts = exe()
    if not ts:
        return ""
    try:
        out = subprocess.run([ts, "status", "--json"], capture_output=True, text=True, timeout=15).stdout
        return json.loads(out).get("Self", {}).get("DNSName", "").rstrip(".")
    except Exception:  # noqa: BLE001
        return ""


def enable_phone_access(port: int, say: Callable[[str], None] = print) -> str:
    """Sign in if needed (opens a browser) and publish HAVOC on the tailnet. Returns the host or ''."""
    ts = exe()
    if not ts:
        say("Tailscale isn't installed. Install it from tailscale.com (free), then try again. "
            "Discord DMs work from anywhere in the meantime.")
        return ""
    if not host():
        say("Signing this PC in to Tailscale: a browser window is opening.")
        subprocess.run([ts, "up"], timeout=600)
    name = host()
    if not name:
        say("Tailscale isn't signed in yet. Finish the sign-in and try again.")
        return ""
    r = subprocess.run([ts, "serve", "--bg", str(port)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        say(f"Tailscale couldn't publish HAVOC: {(r.stderr or r.stdout).strip()} Turn on HTTPS certificates "
            "in the Tailscale admin console (DNS page), then try again.")
        return name
    say(f"Phone access is on: https://{name}")
    return name
