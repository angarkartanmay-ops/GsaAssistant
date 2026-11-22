"""PC control: apps, URLs, files, PowerShell, media keys, system status, power."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

import psutil

from .common import blocking
from .registry import tool

IS_WIN = platform.system() == "Windows"

# Friendly names -> what to launch on Windows. Anything else is tried as-is via `start`.
APP_ALIASES = {
    "chrome": "chrome", "edge": "msedge", "browser": "msedge", "firefox": "firefox",
    "discord": "discord:", "whatsapp": "whatsapp:", "spotify": "spotify:",
    "vscode": "code", "vs code": "code", "code": "code", "notepad": "notepad",
    "explorer": "explorer", "files": "explorer", "file explorer": "explorer",
    "calculator": "calc", "calc": "calc", "terminal": "wt", "cmd": "cmd", "powershell": "powershell",
    "settings": "ms-settings:", "task manager": "taskmgr", "paint": "mspaint",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "teams": "msteams:",
    "camera": "microsoft.windows.camera:", "snipping tool": "ms-screenclip:", "outlook": "outlook",
}
WEB_ALIASES = {
    "gmail": "https://mail.google.com", "calendar": "https://calendar.google.com",
    "drive": "https://drive.google.com", "youtube": "https://youtube.com", "meet": "https://meet.google.com",
    "gemini": "https://gemini.google.com", "docs": "https://docs.google.com", "forms": "https://forms.google.com",
}


@tool("open_app", "Open an app or website by name (chrome, discord, whatsapp, vscode, spotify, gmail, drive...).",
      params={"name": "App or site name"}, group="pc")
async def open_app(rt: Any, name: str) -> str:
    key = name.strip().lower()
    if key in WEB_ALIASES:
        webbrowser.open(WEB_ALIASES[key])
        return f"Opened {key}."
    if key == "dashboard" and rt.cfg.dashboard.url:
        webbrowser.open(rt.cfg.dashboard.url)
        return "Opened the ambassador dashboard."
    target = APP_ALIASES.get(key, name.strip())
    if IS_WIN:
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        exe = shutil.which(target)
        if not exe:
            return f"Can't find an app called '{name}' on this machine."
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Launching {name}."


@tool("open_url", "Open a URL in the default browser.", params={"url": "The URL"}, group="pc")
async def open_url(rt: Any, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}"


def _allowed(cfg: Any, path: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(path))).resolve()
    roots = [Path(os.path.expanduser(d)).resolve() for d in cfg.safety.allowed_dirs]
    if not any(p == r or r in p.parents for r in roots):
        raise PermissionError(f"{p} is outside the allowed folders: {', '.join(map(str, roots))}. "
                              "Add it to safety.allowed_dirs in config.yaml if you want me in there.")
    return p


@tool("list_dir", "List files in a folder (Documents, Desktop, Downloads by default).",
      params={"path": "Folder path, e.g. ~/Documents/GSA"}, group="pc")
async def list_dir(rt: Any, path: str = "~/Documents") -> str:
    p = _allowed(rt.cfg, path)
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:100]
    return "\n".join(("[dir] " if i.is_dir() else "") + i.name for i in items) or "(empty)"


@tool("read_file", "Read a text file.", params={"path": "File path"}, group="pc")
async def read_file(rt: Any, path: str) -> str:
    p = _allowed(rt.cfg, path)
    if p.suffix.lower() == ".pdf":
        return "PDFs aren't supported for reading yet; open it with open_app instead."
    return p.read_text(encoding="utf-8", errors="replace")[:3200]


@tool("write_file", "Create or overwrite a text file (notes, drafts, reports).",
      params={"path": "File path", "content": "Full file content"},
      confirm=lambda rt, path="", **_: _exists(rt, path),
      preview=lambda rt, path="", content="", **_: f"Overwrite {path}:\n{content[:600]}", group="pc")
async def write_file(rt: Any, path: str, content: str) -> str:
    p = _allowed(rt.cfg, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {p}"


def _exists(rt: Any, path: str) -> bool:
    try:
        return _allowed(rt.cfg, path).exists()
    except PermissionError:
        return False


def shell_needs_confirm(rt: Any, command: str = "", **_: Any) -> bool:
    if not rt.cfg.safety.confirm_shell:
        return False
    first = command.strip().split("|")[0].strip()
    if any(c in command for c in (";", "&&", "||", ">", "`", "$(")):
        return True
    return not any(first.lower().startswith(a.lower()) for a in rt.cfg.safety.shell_allowlist)


def _run_shell(command: str, timeout: int = 60) -> str:
    if IS_WIN:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-lc", command]
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0)
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    out = (cp.stdout or "") + (("\n[stderr]\n" + cp.stderr) if cp.stderr.strip() else "")
    return f"exit {cp.returncode}\n{out.strip()[:3000]}"


@tool("run_powershell", "Run a PowerShell command on the PC and return its output. Read-only commands run "
      "straight away; anything else waits for the user's yes.",
      params={"command": "The PowerShell command"}, confirm=shell_needs_confirm,
      preview=lambda rt, command="", **_: f"Run in PowerShell:\n{command}", group="pc")
async def run_powershell(rt: Any, command: str) -> str:
    return await blocking(_run_shell, command)


def _gpu() -> str:
    if not shutil.which("nvidia-smi"):
        return "GPU: nvidia-smi not found"
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip()
        name, util, used, total, temp = [x.strip() for x in out.split(",")]
        return f"GPU: {name}, {util}% load, VRAM {used}/{total} MiB, {temp}°C"
    except Exception as e:  # noqa: BLE001
        return f"GPU: unreadable ({e})"


@tool("system_status", "CPU, RAM, GPU/VRAM, disk and battery status.", group="pc")
async def system_status(rt: Any) -> str:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.expanduser("~"))
    lines = [f"CPU: {psutil.cpu_percent(interval=0.5)}%",
             f"RAM: {vm.used / 2**30:.1f}/{vm.total / 2**30:.1f} GB ({vm.percent}%)",
             await blocking(_gpu),
             f"Disk: {disk.free / 2**30:.0f} GB free of {disk.total / 2**30:.0f} GB"]
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bat:
        lines.append(f"Battery: {bat.percent:.0f}%{' charging' if bat.power_plugged else ''}")
    return "\n".join(lines)


MEDIA_KEYS = {"play": "play/pause media", "pause": "play/pause media", "next": "next track",
              "previous": "previous track", "mute": "volume mute", "volume_up": "volume up",
              "volume_down": "volume down"}


@tool("media_control", "Control media playback and volume.",
      params={"action": "play | pause | next | previous | mute | volume_up | volume_down",
              "times": "Repeat count for volume steps"}, group="pc")
async def media_control(rt: Any, action: str, times: int = 1) -> str:
    key = MEDIA_KEYS.get(action.strip().lower().replace(" ", "_"))
    if not key:
        return f"Unknown media action '{action}'. Use: {', '.join(MEDIA_KEYS)}"
    try:
        import keyboard  # type: ignore[import-not-found]
    except ImportError:
        return "Media keys need the 'keyboard' package (installed on Windows by setup.ps1)."
    for _ in range(max(1, min(times, 20))):
        keyboard.send(key)
    return f"{action} done."


POWER = {
    "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
    "restart": ["shutdown", "/r", "/t", "10"],
    "shutdown": ["shutdown", "/s", "/t", "10"],
}


@tool("power_action", "Lock, sleep, restart or shut down the PC.",
      params={"action": "lock | sleep | restart | shutdown"},
      confirm=lambda rt, action="", **_: action.strip().lower() != "lock",
      preview=lambda rt, action="", **_: f"{action.capitalize()} the PC (in 10s for restart/shutdown)", group="pc")
async def power_action(rt: Any, action: str) -> str:
    argv = POWER.get(action.strip().lower())
    if not argv:
        return f"Unknown power action '{action}'."
    if not IS_WIN:
        return "Power actions are wired for Windows only."
    subprocess.Popen(argv)
    return f"{action.capitalize()} initiated."


@tool("clipboard", "Read the clipboard, or set it to some text.",
      params={"set_text": "Text to put on the clipboard; leave empty to read it"}, group="pc")
async def clipboard(rt: Any, set_text: str = "") -> str:
    if not IS_WIN:
        return "Clipboard access is wired for Windows only."
    if set_text:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                       input=set_text, text=True, timeout=10)
        return "Copied to clipboard."
    out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                         capture_output=True, text=True, timeout=10).stdout
    return out.strip()[:3000] or "(clipboard is empty)"
