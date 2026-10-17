# core/cookies.py
"""Cookie settings shared by the auth endpoints.

Production defaults are ``Secure`` + ``SameSite=None`` (cross-site SPA/API).
For local HTTP development set ``COOKIE_SECURE=false`` (SameSite then
automatically falls back to ``lax`` unless overridden).
"""
import os

REFRESH_TOKEN_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


COOKIE_SECURE = _env_bool("COOKIE_SECURE", True)
COOKIE_SAMESITE = os.getenv(
    "COOKIE_SAMESITE", "none" if COOKIE_SECURE else "lax"
).lower()


def refresh_cookie_options() -> dict:
    return {
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "path": "/",
        "max_age": REFRESH_TOKEN_MAX_AGE,
    }


def delete_cookie_options() -> dict:
    return {
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "path": "/",
    }
