"""Read/write config.yaml + .env for the setup wizard and the HUD's Connections screen.

Secrets live only in .env on this PC. The UI can set or clear them but never reads them back:
`view()` reports whether each secret is set, not its value.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Any

import yaml

from . import config as config_mod
from .config import ROOT, Config

# UI field -> .env variable. Values never leave this PC.
SECRETS = {
    "gmail.app_password": "GMAIL_APP_PASSWORD",
    "gmail.official_app_password": "OFFICIAL_MAIL_APP_PASSWORD",
    "discord.token": "DISCORD_BOT_TOKEN",
    "server.pin": "HAVOC_PIN",
}
# Non-secret values that also live in .env (addresses).
ENV_PLAIN = {
    "gmail.address": "GMAIL_ADDRESS",
    "gmail.official_address": "OFFICIAL_MAIL_ADDRESS",
}
# Non-secret settings stored in config.yaml, with their types.
CONFIG_FIELDS: dict[str, type] = {
    "assistant.user_name": str, "assistant.address_as": str, "assistant.sass": int,
    "gmail.sender_name": str, "gmail.official_auth": str, "gmail.gsa_query": str,
    "gmail.send_mode": str, "gmail.signature": str,
    "dashboard.url": str,
    "discord.guild_id": int, "discord.owner_user_id": int, "discord.owner_username": str,
    "discord.default_channel": str,
    "discord.post_as_name": str,
    "whatsapp.group_name": str,
    "voice.tts_voice": str, "voice.enabled": bool,
    "server.remote_hosts": list,
}


class SettingsError(ValueError):
    pass


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or config_mod.env_path()
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def write_env(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Set (or with None, remove) keys, keeping everything else in the file."""
    path = path or config_mod.env_path()
    env = read_env(path)
    for k, v in updates.items():
        if v is None:
            env.pop(k, None)
        else:
            if "\n" in v or "\r" in v:
                raise SettingsError(f"{k} can't contain line breaks.")
            env[k] = v
    env.setdefault("WA_BRIDGE_TOKEN", secrets.token_hex(16))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")


def read_config_yaml(path: Path | None = None) -> dict:
    path = path or config_mod.config_path()
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    example = ROOT / "config.example.yaml"
    return yaml.safe_load(example.read_text(encoding="utf-8")) if example.exists() else {}


def write_config_yaml(data: dict, path: Path | None = None) -> None:
    Config.model_validate(data)  # refuse to write something that won't load
    path = path or config_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _get(d: dict, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def _set(d: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def _coerce(field: str, typ: type, value: Any) -> Any:
    if typ is int:
        if value in ("", None):
            return 0
        if not re.fullmatch(r"-?\d+", str(value).strip()):
            raise SettingsError(f"{field} must be a number.")
        return int(str(value).strip())
    if typ is bool:
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
    if typ is list:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value or "").split(",") if v.strip()]
    return str(value or "").strip()


def view(cfg: Config) -> dict:
    """What the Connections screen shows. Secrets appear only as set/not set."""
    env = read_env()
    data = cfg.model_dump()
    fields = {f: _get(data, f) for f in CONFIG_FIELDS}
    fields.update({f: env.get(var, "") for f, var in ENV_PLAIN.items()})
    secrets_set = {f: bool(env.get(var)) for f, var in SECRETS.items()}
    return {"fields": fields, "secrets": secrets_set,
            "oauth_client_present": Path(cfg.gmail.oauth_client_file).exists()}


def apply(payload: dict) -> list[str]:
    """Apply a partial update from the UI. Returns the list of fields changed.
    Secrets: a non-empty string sets it, `null` clears it, absent/empty leaves it alone."""
    changed: list[str] = []
    data = read_config_yaml()
    env_updates: dict[str, str | None] = {}
    for field, value in (payload.get("fields") or {}).items():
        if field in CONFIG_FIELDS:
            new = _coerce(field, CONFIG_FIELDS[field], value)
            if field == "assistant.sass" and not 0 <= new <= 3:
                raise SettingsError("Sass goes from 0 to 3.")
            if field == "gmail.official_auth" and new not in ("app_password", "oauth"):
                raise SettingsError("Official mail sign-in must be app_password or oauth.")
            if field == "gmail.send_mode" and new not in ("draft", "smtp"):
                raise SettingsError("Sending must be draft or smtp.")
            if _get(data, field) != new:
                _set(data, field, new)
                changed.append(field)
        elif field in ENV_PLAIN:
            v = str(value or "").strip()
            if v and "@" not in v:
                raise SettingsError(f"{field} doesn't look like an email address.")
            env_updates[ENV_PLAIN[field]] = v or None
            changed.append(field)
        else:
            raise SettingsError(f"Unknown setting {field}.")
    for field, value in (payload.get("secrets") or {}).items():
        if field not in SECRETS:
            raise SettingsError(f"Unknown secret {field}.")
        if value is None:
            env_updates[SECRETS[field]] = None
            changed.append(field)
        elif str(value).strip():
            v = str(value).strip()
            if field.endswith("app_password"):
                v = v.replace(" ", "")
            if field == "server.pin" and not re.fullmatch(r"\d{4,12}", v):
                raise SettingsError("The PIN must be 4 to 12 digits.")
            env_updates[SECRETS[field]] = v
            changed.append(field)
    if changed:
        write_config_yaml(data)
        if env_updates:
            write_env(env_updates)
    return changed
