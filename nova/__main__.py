"""python -m nova <command>

  run              start everything: HUD, voice, connectors, background alerts
  chat             terminal chat (add --voice to also speak replies)
  setup            first-time wizard: writes config.yaml + .env, downloads voice models
  login-dashboard  open a browser once to sign in to the ambassador dashboard
  login-mail       one-time Google sign-in for a mail account set to OAuth
  say "text"       speak a line in Nova's voice (or --out file.wav)
  doctor           check every component and tell you what to fix
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import DATA_DIR, MODELS_DIR, ROOT, load_config


def setup_logging(verbose: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(DATA_DIR / "nova.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[fh, sh],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "discord", "faster_whisper", "urllib3", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------- run
def open_window(url: str) -> None:
    if platform.system() == "Windows":
        candidates = [shutil.which("msedge"),
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
        for exe in candidates:
            if exe and Path(exe).exists():
                subprocess.Popen([exe, f"--app={url}", "--window-size=1440,900"])
                return
    webbrowser.open(url)


def start_tray(url: str, on_quit) -> None:  # noqa: ANN001
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), outline=(255, 181, 71, 200), width=4)
    d.ellipse((20, 20, 44, 44), fill=(79, 209, 255, 255))
    menu = pystray.Menu(pystray.MenuItem("Open HUD", lambda: open_window(url), default=True),
                        pystray.MenuItem("Quit", lambda icon: (icon.stop(), on_quit())))
    icon = pystray.Icon("nova", img, "N.O.V.A.", menu)
    threading.Thread(target=icon.run, daemon=True).start()


async def cmd_run(args: argparse.Namespace) -> None:
    import uvicorn

    from .runtime import Runtime
    from .server.app import create_app

    rt = Runtime()
    cfg = rt.cfg
    status = await rt.start(voice=not args.no_voice)
    llm = status["llm"]
    if not llm.get("ok"):
        print(f"[!] Ollama isn't reachable at {cfg.llm.host}. Start the Ollama app, then restart Nova.")
    elif not llm.get("model_ready"):
        print(f"[!] Model {cfg.llm.model} isn't pulled. Run: ollama pull {cfg.llm.model}")
    url = f"http://{cfg.server.host}:{cfg.server.port}"
    server = uvicorn.Server(uvicorn.Config(create_app(rt), host=cfg.server.host, port=cfg.server.port,
                                           log_level="warning"))
    print(f"{cfg.assistant.name} online at {url}  (voice: {'on' if rt.voice else 'off'})")
    host = tailscale_host()
    if host and cfg.server.pin:
        print(f"Phone app: https://{host}")
    if cfg.server.open_window and not args.no_window:
        threading.Timer(1.5, open_window, args=(url,)).start()
    loop = asyncio.get_running_loop()
    start_tray(url, lambda: loop.call_soon_threadsafe(setattr, server, "should_exit", True))
    try:
        await server.serve()
    finally:
        await rt.stop()


# ---------------------------------------------------------------- chat
async def cmd_chat(args: argparse.Namespace) -> None:
    from rich.console import Console
    from rich.markdown import Markdown

    from .runtime import Runtime

    console = Console()
    rt = Runtime()
    await rt.start(voice=False, scheduler=False)
    if args.voice:
        from .voice.tts import TTS
        tts = TTS(rt.cfg.voice)
    name = rt.cfg.assistant.spoken_name.upper()
    console.print(f"[bold red]{rt.cfg.assistant.name}[/] online. Type 'exit' to leave, 'reset' to clear memory.\n")

    async def on_event(ev: dict) -> None:
        if ev["type"] == "tool" and ev.get("status") == "running":
            console.print(f"  [dim]> {ev['name'].replace('_', ' ')}[/]")
        elif ev["type"] == "confirm":
            console.print(f"[yellow]Staged for approval:[/]\n{ev['preview']}")

    try:
        while True:
            try:
                text = await asyncio.to_thread(console.input, "[bold]you[/] > ")
            except (EOFError, KeyboardInterrupt):
                break
            if text.strip().lower() in {"exit", "quit", "bye"}:
                break
            if text.strip().lower() == "reset":
                rt.agent.reset()
                console.print("[dim]memory cleared[/]")
                continue
            if not text.strip():
                continue
            with console.status("[red]thinking...[/]", spinner="dots"):
                reply = await rt.agent.respond(text, emit=on_event)
            console.print(f"[bold red]{name}[/] >", Markdown(reply))
            if args.voice:
                from .brain.antislop import for_speech
                await asyncio.to_thread(tts.speak, for_speech(reply))
    finally:
        await rt.stop()


# ---------------------------------------------------------------- setup
KOKORO_FILES = {
    "kokoro-v1.0.int8.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def download_models() -> None:
    import httpx
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        dest = MODELS_DIR / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"  {name}: already there")
            continue
        print(f"  downloading {name} ...", flush=True)
        tmp = dest.with_suffix(".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r    {done * 100 // total}%", end="", flush=True)
        tmp.replace(dest)
        print()
    print("  Whisper models download automatically on first use.")


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    import getpass
    suffix = f" [{default}]" if default and not secret else ""
    val = (getpass.getpass if secret else input)(f"{prompt}{suffix}: ").strip()
    return val or default


def cmd_setup(args: argparse.Namespace) -> None:
    import yaml

    print("\nN.O.V.A. setup. Press Enter to skip anything; you can edit config.yaml and .env later.\n")
    cfg_path = ROOT / "config.yaml"
    env_path = ROOT / ".env"
    base = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    if cfg_path.exists():
        base.update(yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {})

    a = base.setdefault("assistant", {})
    a["user_name"] = ask("Your first name", a.get("user_name", "Tanmay"))
    a["address_as"] = ask("What should Nova call you", a.get("address_as", "Sir"))
    d = base.setdefault("dashboard", {})
    d["url"] = ask("Ambassador dashboard URL (the web app with your tasks)", d.get("url", ""))
    dc = base.setdefault("discord", {})
    gid = ask("Discord server (guild) ID, right-click server > Copy Server ID", str(dc.get("guild_id", "") or ""))
    dc["guild_id"] = int(gid) if gid.isdigit() else 0
    oid = ask("Your Discord user ID (DMs from you become commands)", str(dc.get("owner_user_id", "") or ""))
    dc["owner_user_id"] = int(oid) if oid.isdigit() else 0
    dc["default_channel"] = ask("Discord channel Nova posts to by default", dc.get("default_channel", "general"))
    dc["post_as_name"] = ask("Name shown on Discord posts", dc.get("post_as_name") or a["user_name"])
    w = base.setdefault("whatsapp", {})
    w["group_name"] = ask("Name of the GSA WhatsApp group (part of it is fine)", w.get("group_name", "GSA"))
    g = base.setdefault("gmail", {})
    g["sender_name"] = ask("Your name as it should appear on emails you send", g.get("sender_name", ""))

    env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    print("\nMail. Secrets are typed here only; never paste them into a chat.")
    env["GMAIL_ADDRESS"] = ask("Gmail address that RECEIVES your GSA mail", env.get("GMAIL_ADDRESS", ""))
    pw = ask("  its App Password (16 letters, myaccount.google.com/apppasswords)", secret=True)
    if pw:
        env["GMAIL_APP_PASSWORD"] = pw.replace(" ", "")
    off = ask("Official address you SEND from (Enter = same as above)", env.get("OFFICIAL_MAIL_ADDRESS", ""))
    if off and off != env["GMAIL_ADDRESS"]:
        env["OFFICIAL_MAIL_ADDRESS"] = off
        how = ask("  Does it allow App Passwords? y = App Password, n = sign in with Google (OAuth)", "y")
        if how.lower().startswith("n"):
            g["official_auth"] = "oauth"
            print("  OK: after setup, follow README > Official mail (OAuth), then run `python -m nova login-mail`.")
        else:
            g["official_auth"] = "app_password"
            opw = ask("  its App Password", secret=True)
            if opw:
                env["OFFICIAL_MAIL_APP_PASSWORD"] = opw.replace(" ", "")
    tok = ask("Discord bot token (from discord.com/developers)", secret=True)
    if tok:
        env["DISCORD_BOT_TOKEN"] = tok
    env.setdefault("WA_BRIDGE_TOKEN", secrets.token_hex(16))

    print("\nPhone access (private, over Tailscale).")
    pin = ask("Choose a PIN for the phone app (4+ digits; Enter keeps the current one)", secret=True)
    if pin:
        env["NOVA_PIN"] = pin
    srv = base.setdefault("server", {})
    host = setup_tailscale(base.get("server", {}).get("port", 7777))
    if host:
        srv["remote_hosts"] = [host]
        print(f"  Phone app: https://{host}  (install Tailscale on the phone, same account)")

    cfg_path.write_text(yaml.safe_dump(base, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"  wrote {cfg_path.name}")
    env_path.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8")
    print(f"  wrote {env_path.name} (keep this file private)")

    if not args.skip_models:
        print("\nVoice models:")
        try:
            download_models()
        except Exception as e:  # noqa: BLE001
            print(f"  download failed: {e}. Re-run `python -m nova setup` later.")
    cfg = load_config()
    if shutil.which("ollama"):
        print(f"\nPulling {cfg.llm.model} with Ollama (about 5 GB, once)...")
        subprocess.run(["ollama", "pull", cfg.llm.model])
    else:
        print("\nOllama isn't installed. Get it from https://ollama.com/download, then run: "
              f"ollama pull {cfg.llm.model}")
    print("\nNext: `python -m nova login-dashboard` (once), then start.bat. Run `python -m nova doctor` any time.")


def tailscale_host() -> str:
    """This PC's Tailscale name, e.g. my-pc.tail1234.ts.net ('' if Tailscale isn't up)."""
    exe = shutil.which("tailscale")
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=15).stdout
        return json.loads(out).get("Self", {}).get("DNSName", "").rstrip(".")
    except Exception:  # noqa: BLE001
        return ""


def setup_tailscale(port: int) -> str:
    exe = shutil.which("tailscale")
    if not exe:
        print("  Tailscale isn't installed (setup.ps1 installs it). Discord DMs still work from anywhere.")
        return ""
    if not tailscale_host():
        print("  Signing this PC in to Tailscale (a browser window opens)...")
        subprocess.run([exe, "up"])
    host = tailscale_host()
    if not host:
        print("  Tailscale isn't signed in; skipping. Re-run setup later.")
        return ""
    r = subprocess.run([exe, "serve", "--bg", str(port)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  `tailscale serve` failed: {(r.stderr or r.stdout).strip()}\n"
              "  Turn on HTTPS certificates in the Tailscale admin console (DNS page), then re-run setup.")
        return host
    return host


# ---------------------------------------------------------------- doctor
async def cmd_doctor(args: argparse.Namespace) -> None:
    from .runtime import Runtime

    cfg = load_config()
    ok, bad = "\u2714", "\u2718"
    rows: list[tuple[bool, str, str]] = []

    rt = Runtime(cfg)
    h = await rt.llm.health()
    rows.append((bool(h.get("ok") and h.get("model_ready")), "Ollama + model",
                 h.get("model", "") if h.get("ok") else f"not reachable at {cfg.llm.host}"))
    if h.get("ok") and not h.get("model_ready"):
        rows[-1] = (False, "Ollama + model", f"run: ollama pull {cfg.llm.model}")

    gpu = shutil.which("nvidia-smi")
    if gpu:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout.strip()
        rows.append((True, "GPU", out))
    else:
        rows.append((False, "GPU", "nvidia-smi not found (voice/LLM will use CPU)"))
    try:
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        rows.append((n > 0, "Whisper GPU (CTranslate2)", f"{n} CUDA device(s), v{ctranslate2.__version__}"))
    except Exception as e:  # noqa: BLE001
        rows.append((False, "Whisper GPU (CTranslate2)", str(e)))

    from .voice.tts import TTS
    rows.append((TTS(cfg.voice).available(), "Kokoro voice files", str(MODELS_DIR)))
    try:
        import sounddevice as sd
        dev = sd.query_devices(kind="input")
        rows.append((True, "Microphone", dev["name"]))
    except Exception as e:  # noqa: BLE001
        rows.append((False, "Microphone", str(e)))

    if rt.gmail.configured:
        try:
            await asyncio.to_thread(rt.gmail.check_login)
            rows.append((True, "Gmail", cfg.gmail.address))
        except Exception as e:  # noqa: BLE001
            rows.append((False, "Gmail", str(e)))
    else:
        rows.append((False, "Gmail", "set GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env"))
    if cfg.gmail.official_address:
        try:
            await asyncio.to_thread(lambda: rt.gmail._imap(rt.gmail.sender).logout())
            rows.append((True, "Official mail (sending)", cfg.gmail.official_address))
        except Exception as e:  # noqa: BLE001
            rows.append((False, "Official mail (sending)", str(e)))
    host = tailscale_host()
    rows.append((bool(host), "Tailscale (phone app)", f"https://{host}" if host else "not signed in / not installed"))
    rows.append((bool(cfg.server.pin), "Phone PIN", "set" if cfg.server.pin else "set NOVA_PIN in .env"))

    prof = Path(cfg.dashboard.profile_dir)
    if not cfg.dashboard.url:
        dash_detail = "set dashboard.url in config.yaml"
    elif not prof.exists():
        dash_detail = "run: python -m nova login-dashboard"
    else:
        dash_detail = cfg.dashboard.url
    rows.append((bool(cfg.dashboard.url) and prof.exists(), "Dashboard", dash_detail))
    rows.append((bool(cfg.discord.token), "Discord token", "set" if cfg.discord.token else "set DISCORD_BOT_TOKEN"))
    try:
        st = await rt.whatsapp.status()
        rows.append((bool(st.get("connected")), "WhatsApp bridge", "linked" if st.get("connected") else "running, scan the QR"))
    except Exception:  # noqa: BLE001
        rows.append((False, "WhatsApp bridge", "not running (start.bat starts it)"))
    try:
        import playwright  # noqa: F401
        rows.append((True, "Playwright", "installed"))
    except ImportError:
        rows.append((False, "Playwright", "pip install playwright"))
    await rt.stop()

    width = max(len(r[1]) for r in rows)
    for good, name, detail in rows:
        print(f" {ok if good else bad}  {name.ljust(width)}  {detail}")


# ---------------------------------------------------------------- misc
def cmd_login_mail(args: argparse.Namespace) -> None:
    from .connectors.google_oauth import access_token
    cfg = load_config()
    targets = []
    if cfg.gmail.auth == "oauth" and cfg.gmail.address:
        targets.append(cfg.gmail.address)
    if cfg.gmail.official_auth == "oauth" and cfg.gmail.official_address:
        targets.append(cfg.gmail.official_address)
    if not targets:
        print("No account is set to OAuth (gmail.auth / gmail.official_auth: oauth). App Passwords need no login.")
        return
    for addr in targets:
        print(f"Signing in {addr} (a browser window opens)...")
        access_token(addr, cfg.gmail.oauth_client_file, interactive=True)
        print("  saved.")


async def cmd_login_dashboard(args: argparse.Namespace) -> None:
    from .connectors.dashboard_browser import DashboardBrowser
    cfg = load_config()
    await DashboardBrowser(cfg.dashboard).login()
    print("Saved. Nova can read the dashboard now.")


def cmd_say(args: argparse.Namespace) -> None:
    from .voice.tts import TTS
    cfg = load_config()
    if args.voice:
        cfg.voice.tts_voice = args.voice
    tts = TTS(cfg.voice)
    if args.out:
        print(tts.save(args.text, args.out))
    else:
        tts.speak(args.text)


def main() -> None:
    p = argparse.ArgumentParser(prog="nova", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--no-voice", action="store_true")
    r.add_argument("--no-window", action="store_true")
    c = sub.add_parser("chat")
    c.add_argument("--voice", action="store_true")
    s = sub.add_parser("setup")
    s.add_argument("--skip-models", action="store_true")
    sub.add_parser("models")
    sub.add_parser("login-dashboard")
    sub.add_parser("login-mail")
    sub.add_parser("doctor")
    sy = sub.add_parser("say")
    sy.add_argument("text")
    sy.add_argument("--out")
    sy.add_argument("--voice", help="voice or blend to try, e.g. bf_emma or 'bf_emma:0.6,bf_isabella:0.4'")
    args = p.parse_args()
    setup_logging(args.verbose)
    if platform.system() == "Windows":
        os.environ.setdefault("PYTHONUTF8", "1")
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    cmd = args.cmd or "run"
    if cmd == "run":
        if not hasattr(args, "no_voice"):
            args.no_voice = args.no_window = False
        asyncio.run(cmd_run(args))
    elif cmd == "chat":
        asyncio.run(cmd_chat(args))
    elif cmd == "setup":
        cmd_setup(args)
    elif cmd == "models":
        download_models()
    elif cmd == "login-mail":
        cmd_login_mail(args)
    elif cmd == "login-dashboard":
        asyncio.run(cmd_login_dashboard(args))
    elif cmd == "doctor":
        asyncio.run(cmd_doctor(args))
    elif cmd == "say":
        cmd_say(args)


if __name__ == "__main__":
    main()
