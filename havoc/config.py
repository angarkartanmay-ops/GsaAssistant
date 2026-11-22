"""Configuration: config.yaml (settings) + .env (secrets).

Everything has a sensible default so the assistant boots with an empty config.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent  # where the code lives
# Where YOUR stuff lives (config.yaml, .env, data/, knowledge/). Same as ROOT for a git checkout;
# the desktop app points it at %LOCALAPPDATA%\HAVOC so updates never touch your data.
HOME = Path(os.environ.get("HAVOC_HOME") or ROOT).resolve()
DATA_DIR = HOME / "data"
MODELS_DIR = DATA_DIR / "models"
KNOWLEDGE_DIR = HOME / "knowledge"


def config_path() -> Path:
    return HOME / "config.yaml"


def env_path() -> Path:
    return HOME / ".env"


class AssistantCfg(BaseModel):
    name: str = "H.A.V.O.C."
    spoken_name: str = "Havoc"
    # Whisper's common mishearings of the name count as the wake word too.
    wake_words: list[str] = ["havoc", "havok", "havic", "havick"]
    user_name: str = "Tanmay"
    # What it calls you. Always "Sir" unless you change it.
    address_as: str = "Sir"
    # Sarcasm and humour level: 0 = none, 1 = light (default), 2 = regular, 3 = full sass.
    # Posts and emails written in your name never get sarcasm, whatever this says.
    sass: int = 1


class LLMCfg(BaseModel):
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    fallback_model: str = "qwen3:4b"
    temperature: float = 0.6
    num_ctx: int = 8192
    history_turns: int = 16
    timeout_s: float = 180.0


class VoiceCfg(BaseModel):
    enabled: bool = True
    wake_enabled: bool = True
    push_to_talk_hotkey: str = "ctrl+alt+m"
    stt_model: str = "small.en"
    wake_model: str = "tiny.en"
    stt_device: str = "auto"  # auto | cuda | cpu
    follow_up_seconds: float = 7.0
    silence_ms: int = 750
    vad_threshold: float = 0.5
    input_device: Optional[str | int] = None
    output_device: Optional[str | int] = None
    # TTS: warm British female voices from Kokoro, blended. Pick another in config.yaml.
    tts_voice: str = "bf_emma:0.6,bf_isabella:0.4"
    tts_lang: str = "en-gb"
    tts_speed: float = 1.05
    kokoro_model: str = "kokoro-v1.0.int8.onnx"
    kokoro_voices: str = "voices-v1.0.bin"
    max_spoken_chars: int = 600


class GmailCfg(BaseModel):
    enabled: bool = True
    imap_host: str = "imap.gmail.com"
    smtp_host: str = "smtp.gmail.com"
    mailbox: str = '"[Gmail]/All Mail"'
    gsa_query: str = (
        '("Student Ambassador" OR "Gemini Student Ambassador" OR GSA OR from:google.com'
        " OR from:geministudentambassador.com) -category:promotions"
    )
    max_results: int = 25
    auth: str = "app_password"  # app_password | oauth (for college/Workspace accounts that block App Passwords)
    oauth_client_file: str = "data/google_oauth_client.json"
    address: str = ""  # filled from GMAIL_ADDRESS
    app_password: str = ""  # filled from GMAIL_APP_PASSWORD
    # Optional separate "official" account that outgoing mail is sent from.
    official_address: str = ""  # filled from OFFICIAL_MAIL_ADDRESS
    official_app_password: str = ""  # filled from OFFICIAL_MAIL_APP_PASSWORD
    official_auth: str = "app_password"
    sender_name: str = ""  # display name on sent mail, e.g. "Tanmay Angarkar"
    # "draft": HAVOC writes the email and opens it ready-to-send in Gmail (your account, no password
    # needed); you press Send. "smtp": HAVOC sends it itself (needs an App Password or OAuth).
    send_mode: str = "smtp"
    signature: str = ""  # appended to emails, e.g. "Tanmay Angarkar\nGoogle Student Ambassador"


class DashboardCfg(BaseModel):
    enabled: bool = True
    url: str = ""
    extra_urls: list[str] = []
    browser_channel: str = "msedge"  # msedge | chrome | chromium
    profile_dir: str = str(DATA_DIR / "browser-profile")
    cdp_url: str = ""  # e.g. http://127.0.0.1:9222 to attach to your real Chrome
    wait_ms: int = 4000
    refresh_minutes: int = 60


class DiscordCfg(BaseModel):
    enabled: bool = True
    token: str = ""  # filled from DISCORD_BOT_TOKEN
    guild_id: int = 0
    owner_user_id: int = 0  # your Discord user id: DMs from you go straight to Havoc
    owner_username: str = ""  # or just your username; HAVOC locks onto its ID on your first DM
    # Posts go through a channel webhook so they show your name and avatar instead of the bot's.
    post_as_webhook: bool = True
    post_as_name: str = ""  # empty = assistant.user_name
    post_as_avatar: str = ""  # image URL; empty = your Discord avatar
    voice_replies: bool = True  # answer DM voice notes with a spoken reply as well
    default_channel: str = "general"
    watch_channels: list[str] = []
    alert_keywords: list[str] = ["deadline", "urgent", "submit", "today", "tomorrow"]


class WhatsAppCfg(BaseModel):
    enabled: bool = True
    bridge_url: str = "http://127.0.0.1:3777"
    bridge_token: str = ""  # filled from WA_BRIDGE_TOKEN
    group_name: str = "GSA"
    alert_keywords: list[str] = ["deadline", "urgent", "submit", "form", "today", "tomorrow"]


class SafetyCfg(BaseModel):
    # You chose "send everything directly". undo_last_post can still pull back Discord/WhatsApp posts.
    confirm_email_send: bool = False
    confirm_discord_post: bool = False
    confirm_whatsapp_send: bool = False
    confirm_shell: bool = True
    shell_allowlist: list[str] = [
        "Get-", "dir", "ls", "pwd", "whoami", "hostname", "ipconfig", "systeminfo",
        "tasklist", "nvidia-smi", "echo", "Test-Connection", "ping", "date", "where",
    ]
    allowed_dirs: list[str] = ["~/Documents", "~/Desktop", "~/Downloads"]


class SchedulerCfg(BaseModel):
    enabled: bool = True
    poll_minutes: int = 15
    briefing_time: str = "08:30"
    speak_alerts: bool = True


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7777
    open_window: bool = True
    # Phone access: requests that don't come from this PC's own browser need this PIN.
    pin: str = ""  # filled from HAVOC_PIN
    remote_hosts: list[str] = []  # e.g. ["my-pc.tail1234.ts.net"]; empty = any Tailscale *.ts.net host


class Config(BaseModel):
    assistant: AssistantCfg = Field(default_factory=AssistantCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    voice: VoiceCfg = Field(default_factory=VoiceCfg)
    gmail: GmailCfg = Field(default_factory=GmailCfg)
    dashboard: DashboardCfg = Field(default_factory=DashboardCfg)
    discord: DiscordCfg = Field(default_factory=DiscordCfg)
    whatsapp: WhatsAppCfg = Field(default_factory=WhatsAppCfg)
    safety: SafetyCfg = Field(default_factory=SafetyCfg)
    scheduler: SchedulerCfg = Field(default_factory=SchedulerCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "havoc.db"


def load_config(path: Path | str | None = None) -> Config:
    load_dotenv(env_path(), override=True)
    path = Path(path) if path else config_path()
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = Config.model_validate(raw)

    # Secrets come from the environment so config.yaml can be shared safely.
    cfg.gmail.address = os.getenv("GMAIL_ADDRESS", cfg.gmail.address)
    cfg.gmail.app_password = os.getenv("GMAIL_APP_PASSWORD", cfg.gmail.app_password).replace(" ", "")
    cfg.discord.token = os.getenv("DISCORD_BOT_TOKEN", cfg.discord.token)
    cfg.whatsapp.bridge_token = os.getenv("WA_BRIDGE_TOKEN", cfg.whatsapp.bridge_token)
    cfg.gmail.official_address = os.getenv("OFFICIAL_MAIL_ADDRESS", cfg.gmail.official_address)
    cfg.gmail.official_app_password = os.getenv("OFFICIAL_MAIL_APP_PASSWORD",
                                                cfg.gmail.official_app_password).replace(" ", "")
    cfg.server.pin = os.getenv("HAVOC_PIN", cfg.server.pin)
    if os.getenv("DASHBOARD_URL"):
        cfg.dashboard.url = os.environ["DASHBOARD_URL"]
    if not Path(cfg.dashboard.profile_dir).is_absolute():
        cfg.dashboard.profile_dir = str(HOME / cfg.dashboard.profile_dir)
    if not Path(cfg.gmail.oauth_client_file).is_absolute():
        cfg.gmail.oauth_client_file = str(HOME / cfg.gmail.oauth_client_file)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_DIR.exists() and (ROOT / "knowledge").exists() and KNOWLEDGE_DIR != ROOT / "knowledge":
        import shutil
        shutil.copytree(ROOT / "knowledge", KNOWLEDGE_DIR)  # first run of the desktop app
    inbox_dir()
    return cfg


def inbox_dir() -> Path:
    """Photos/files sent from your phone land here, ready to forward. Only files in here can be
    attached to outgoing posts, so a misheard request can't mail out arbitrary files."""
    d = DATA_DIR / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d
