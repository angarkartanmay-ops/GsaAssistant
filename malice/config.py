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

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = DATA_DIR / "models"
KNOWLEDGE_DIR = ROOT / "knowledge"


class AssistantCfg(BaseModel):
    name: str = "M.A.L.I.C.E."
    spoken_name: str = "Malice"
    # Whisper's common mishearings of the name count as the wake word too.
    wake_words: list[str] = ["malice", "malis", "mallis", "malise", "alice"]
    user_name: str = "Tanmay"
    # What it calls you out loud. Ultron-ish options: "Tanmay", "boss", "creator".
    address_as: str = "Tanmay"


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
    # TTS
    tts_voice: str = "am_onyx:0.65,am_michael:0.35"
    tts_speed: float = 0.92
    menace: float = 2.0  # 0 = clean voice, 3 = full synthetic menace
    kokoro_model: str = "kokoro-v1.0.int8.onnx"
    kokoro_voices: str = "voices-v1.0.bin"
    max_spoken_chars: int = 600


class GmailCfg(BaseModel):
    enabled: bool = True
    imap_host: str = "imap.gmail.com"
    smtp_host: str = "smtp.gmail.com"
    mailbox: str = '"[Gmail]/All Mail"'
    gsa_query: str = (
        '("Student Ambassador" OR "Gemini Student Ambassador" OR GSA OR from:google.com)'
        " -category:promotions"
    )
    max_results: int = 25
    address: str = ""  # filled from GMAIL_ADDRESS
    app_password: str = ""  # filled from GMAIL_APP_PASSWORD


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
    owner_user_id: int = 0  # your Discord user id: DMs from you go straight to Malice
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
    confirm_email_send: bool = True
    confirm_discord_post: bool = True
    confirm_whatsapp_send: bool = False  # you chose auto-send
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
        return DATA_DIR / "malice.db"


def load_config(path: Path | str | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    path = Path(path) if path else ROOT / "config.yaml"
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = Config.model_validate(raw)

    # Secrets come from the environment so config.yaml can be shared safely.
    cfg.gmail.address = os.getenv("GMAIL_ADDRESS", cfg.gmail.address)
    cfg.gmail.app_password = os.getenv("GMAIL_APP_PASSWORD", cfg.gmail.app_password).replace(" ", "")
    cfg.discord.token = os.getenv("DISCORD_BOT_TOKEN", cfg.discord.token)
    cfg.whatsapp.bridge_token = os.getenv("WA_BRIDGE_TOKEN", cfg.whatsapp.bridge_token)
    if os.getenv("DASHBOARD_URL"):
        cfg.dashboard.url = os.environ["DASHBOARD_URL"]
    if not Path(cfg.dashboard.profile_dir).is_absolute():
        cfg.dashboard.profile_dir = str(ROOT / cfg.dashboard.profile_dir)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return cfg
