"""Passwords and tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import User, get_session

SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me")
TOKEN_HOURS = 12
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    again = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return hmac.compare_digest(again, digest)


def make_token(user: User) -> str:
    now = datetime.now(UTC)
    return jwt.encode({"sub": user.id, "iat": now, "exp": now + timedelta(hours=TOKEN_HOURS)}, SECRET, "HS256")


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    if creds is None:
        raise HTTPException(401, "Not logged in")
    try:
        claims = jwt.decode(creds.credentials, SECRET, ["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid token") from None
    user = session.get(User, claims["sub"])
    if user is None:
        raise HTTPException(401, "Unknown user")
    return user
