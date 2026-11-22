"""OAuth for Gmail accounts that block App Passwords (common on college / Workspace accounts).

One-time: create a free OAuth client (Desktop app) in Google Cloud Console, save its JSON as
data/google_oauth_client.json, then run `python -m nova login-mail`. Tokens are stored per
address in data/ and refreshed automatically; IMAP and SMTP then log in with XOAUTH2.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config as config_mod

SCOPES = ["https://mail.google.com/"]


class OAuthError(RuntimeError):
    pass


def token_path(address: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", address.lower())
    return config_mod.DATA_DIR / f"google_token_{safe}.json"


def access_token(address: str, client_file: str, interactive: bool = False) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as e:
        raise OAuthError("OAuth needs google-auth-oauthlib: pip install google-auth-oauthlib") from e
    path = token_path(address)
    creds = Credentials.from_authorized_user_file(str(path), SCOPES) if path.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
    if creds and creds.valid:
        return creds.token
    if not interactive:
        raise OAuthError(f"No Google sign-in stored for {address}. Run: python -m nova login-mail")
    if not Path(client_file).exists():
        raise OAuthError(f"OAuth client file not found: {client_file}. See README > Official mail.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    creds = flow.run_local_server(port=0, login_hint=address, prompt="consent")
    path.write_text(creds.to_json(), encoding="utf-8")
    return creds.token
