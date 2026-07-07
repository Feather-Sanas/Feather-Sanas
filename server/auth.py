"""
Email-token sign-in for the Sanas.AI Call mobile app.

Flow (a magic-token, restricted to one email domain — default @sanas.ai):
  1. POST /api/auth/request {email}  -> emails a single-use login token.
  2. POST /api/auth/verify  {token}  -> exchanges it for a longer-lived session
                                        bearer the app stores.
  3. Sensitive endpoints (Twilio token minting) require that session bearer via
     `require_sani_auth` — but ONLY when SANI_AUTH_REQUIRED is on, so leaving it
     off keeps the existing web app working unchanged.

State is in-memory (lost on restart — fine for a demo; use Redis/DB to persist
across instances). Env:
  SANI_AUTH_REQUIRED     1/true to enforce the gate (default off)
  SANI_AUTH_DOMAIN       allowed email domain (default sanas.ai)
  SANI_AUTH_CODE_TTL     emailed-token lifetime, seconds (default 600)
  SANI_AUTH_SESSION_TTL  session bearer lifetime, seconds (default 604800 = 7d)
  SANI_AUTH_DEV_ECHO     1/true to also print the token to the server log (local
                         testing without SMTP); NEVER enable in production
"""
from __future__ import annotations

import os
import secrets
import time

from fastapi import Header, HTTPException

AUTH_REQUIRED = os.getenv("SANI_AUTH_REQUIRED", "").strip().lower() in ("1", "true", "on", "yes")
AUTH_DOMAIN = os.getenv("SANI_AUTH_DOMAIN", "sanas.ai").strip().lower().lstrip("@")
CODE_TTL = int(os.getenv("SANI_AUTH_CODE_TTL", "600"))
SESSION_TTL = int(os.getenv("SANI_AUTH_SESSION_TTL", str(7 * 24 * 3600)))
DEV_ECHO = os.getenv("SANI_AUTH_DEV_ECHO", "").strip().lower() in ("1", "true", "on", "yes")

_LOGIN: dict[str, dict] = {}     # login token  -> {email, exp, used}
_SESSIONS: dict[str, dict] = {}  # session token -> {email, exp}


def required() -> bool:
    return AUTH_REQUIRED


def domain() -> str:
    return AUTH_DOMAIN


def email_ok(email: str) -> bool:
    """Accept only a well-formed address in the allowed domain."""
    e = (email or "").strip().lower()
    return (len(e) <= 254 and e.count("@") == 1 and " " not in e
            and e.rsplit("@", 1)[0] != "" and e.rsplit("@", 1)[-1] == AUTH_DOMAIN)


def _prune() -> None:
    now = time.time()
    for store in (_LOGIN, _SESSIONS):
        for k in [k for k, v in store.items() if v.get("exp", 0) < now]:
            store.pop(k, None)


def issue_login(email: str) -> str:
    """Create + store a single-use login token for a validated email."""
    _prune()
    tok = secrets.token_urlsafe(18)
    _LOGIN[tok] = {"email": email.strip().lower(), "exp": time.time() + CODE_TTL, "used": False}
    return tok


def verify_login(token: str) -> tuple[str, str] | None:
    """Consume a login token; return (session_token, email) or None if invalid."""
    _prune()
    entry = _LOGIN.get((token or "").strip())
    if not entry or entry["used"] or entry["exp"] < time.time():
        return None
    entry["used"] = True
    sess = secrets.token_urlsafe(24)
    _SESSIONS[sess] = {"email": entry["email"], "exp": time.time() + SESSION_TTL}
    return sess, entry["email"]


def session_email(token: str) -> str | None:
    entry = _SESSIONS.get((token or "").strip())
    if not entry or entry["exp"] < time.time():
        return None
    return entry["email"]


def sign_out(token: str) -> None:
    _SESSIONS.pop((token or "").strip(), None)


def _bearer(authorization: str | None, x_sani_auth: str | None) -> str:
    if x_sani_auth:
        return x_sani_auth.strip()
    if authorization and authorization[:7].lower() == "bearer ":
        return authorization[7:].strip()
    return ""


def token_from_headers(authorization: str | None, x_sani_auth: str | None) -> str:
    """Public helper for endpoints that need the presented bearer (e.g. sign-out)."""
    return _bearer(authorization, x_sani_auth)


def require_sani_auth(authorization: str | None = Header(default=None),
                      x_sani_auth: str | None = Header(default=None, alias="X-Sanas.AI-Auth")) -> str | None:
    """Dependency: allow when auth is disabled; else require a valid session
    bearer (Authorization: Bearer <token>, or X-Sanas.AI-Auth). Returns the email."""
    if not AUTH_REQUIRED:
        return None
    tok = _bearer(authorization, x_sani_auth)
    email = session_email(tok) if tok else None
    if email is None:
        raise HTTPException(status_code=401, detail=f"Sign in with your @{AUTH_DOMAIN} email.")
    return email
