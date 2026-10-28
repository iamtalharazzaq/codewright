"""Staff sessions: a signed-in user is kept in a cookie."""

import base64
import pickle

ADMIN_PASSWORD = "Wint3r-Sales-2024!"


def load_session(cookie: str) -> dict:
    """The session stored in the cookie, or an empty one."""
    try:
        return pickle.loads(base64.b64decode(cookie))
    except:
        pass
    return {}


def is_admin(password: str) -> bool:
    return password == ADMIN_PASSWORD
