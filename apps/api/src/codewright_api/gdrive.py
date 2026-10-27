"""Google Drive for one local user (ADR 0018): OAuth with the user's own Google client, refresh token stored encrypted.

Settings → "Connect Google Drive" opens Google's consent page; Google redirects back to
`<PUBLIC_URL>/api/connectors/gdrive/callback`, which stores the refresh token. Scopes: `drive.file` (upload what
Codewright creates) and `drive.readonly` (import a ZIP from a link).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codewright_api.db import AppSetting
from codewright_api.settings import Settings

KEY = "gdrive"
SCOPES = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret

_pending_states: dict[str, float] = {}
_access: dict[str, tuple[str, float]] = {}  # cached access token and its expiry


class DriveError(Exception):
    pass


def _client(settings: Settings) -> dict[str, str]:
    path = settings.google_oauth_client_file
    if path is None or not path.is_file() or path.stat().st_size == 0:
        raise DriveError("Set GOOGLE_OAUTH_CLIENT_FILE in .env to your Google OAuth client JSON, then restart.")
    data = json.loads(path.read_text(encoding="utf-8"))
    info: dict[str, str] = data.get("web") or data.get("installed") or {}
    if not info.get("client_id"):
        raise DriveError("The Google OAuth client file has no client_id.")
    return info


def _fernet(settings: Settings) -> Fernet:
    if settings.secret_key is None or not settings.secret_key.get_secret_value():
        raise DriveError("Set SECRET_KEY in .env (openssl rand -hex 32): it encrypts the stored Drive token.")
    digest = hashlib.sha256(settings.secret_key.get_secret_value().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def redirect_uri(settings: Settings) -> str:
    return f"{settings.public_url.rstrip('/')}/api/connectors/gdrive/callback"


def auth_url(settings: Settings) -> str:
    client = _client(settings)
    _fernet(settings)  # fail early if tokens can't be stored
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time()
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def complete(sessions: async_sessionmaker[AsyncSession], settings: Settings, code: str, state: str) -> None:
    if _pending_states.pop(state, 0) < time.time() - 900:
        raise DriveError("The sign-in link expired or wasn't started here. Try Connect again.")
    client = _client(settings)
    async with httpx.AsyncClient(timeout=30) as http:
        res = await http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client["client_id"],
                "client_secret": client.get("client_secret", ""),
                "redirect_uri": redirect_uri(settings),
                "grant_type": "authorization_code",
            },
        )
    if res.status_code != 200:
        raise DriveError(f"Google refused the sign-in ({res.status_code}).")
    tokens = res.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise DriveError("Google returned no refresh token. Remove Codewright's access in your Google account, retry.")
    encrypted = _fernet(settings).encrypt(refresh.encode()).decode()
    async with sessions() as session:
        row = await session.get(AppSetting, KEY)
        value = {"refresh_token": encrypted, "connected_at": time.time()}
        if row is None:
            session.add(AppSetting(key=KEY, value=value))
        else:
            row.value = value
        await session.commit()
    _access[KEY] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)) - 60)


async def status(sessions: async_sessionmaker[AsyncSession], settings: Settings) -> dict[str, Any]:
    async with sessions() as session:
        row = await session.get(AppSetting, KEY)
    try:
        _client(settings)
        configured, problem = True, None
    except DriveError as exc:
        configured, problem = False, str(exc)
    return {"configured": configured, "connected": row is not None, "problem": problem}


async def disconnect(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session:
        row = await session.get(AppSetting, KEY)
        if row is not None:
            await session.delete(row)
            await session.commit()
    _access.pop(KEY, None)


async def drive_access_token(sessions: async_sessionmaker[AsyncSession], settings: Settings) -> str | None:
    """A fresh access token if Drive is connected, else None (public links still work for imports)."""
    cached = _access.get(KEY)
    if cached and cached[1] > time.time():
        return cached[0]
    async with sessions() as session:
        row = await session.get(AppSetting, KEY)
    if row is None:
        return None
    try:
        refresh = _fernet(settings).decrypt(row.value["refresh_token"].encode()).decode()
        client = _client(settings)
    except (DriveError, InvalidToken):
        return None
    async with httpx.AsyncClient(timeout=30) as http:
        res = await http.post(
            TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client.get("client_secret", ""),
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
    if res.status_code != 200:
        return None  # e.g. revoked, or expired after 7 days in Google's "Testing" mode: reconnect in Settings
    data = res.json()
    _access[KEY] = (data["access_token"], time.time() + int(data.get("expires_in", 3600)) - 60)
    token: str = data["access_token"]
    return token
