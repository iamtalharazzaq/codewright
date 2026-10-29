"""Passwords and sign-in tokens, with the standard library only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_SECONDS = 7 * 24 * 3600


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _, digest_hex = stored.partition("$")
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, user_id: int, now: float | None = None) -> str:
    claims = {"sub": user_id, "exp": int((now or time.time()) + TOKEN_SECONDS)}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"{payload}.{_sign(secret, payload)}"


def read_token(secret: str, token: str, now: float | None = None) -> int | None:
    """The user id in a valid, unexpired token; None otherwise."""
    payload, _, signature = token.partition(".")
    if not payload or not hmac.compare_digest(_sign(secret, payload), signature):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return None
    if claims.get("exp", 0) < (now or time.time()):
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, int) else None
