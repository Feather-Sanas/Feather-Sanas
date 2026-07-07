"""
Minimal SMTP mailer for the "Book a demo / More information" flow.

Credentials live ONLY in server/.env (never the browser, never git). Configure:
  SMTP_HOST, SMTP_PORT (587 STARTTLS default, or 465 for SSL), SMTP_USER,
  SMTP_PASS, SMTP_FROM (defaults to SMTP_USER). If unset, available() is False
  and send() returns (False, reason) so the caller degrades gracefully — the
  booking link still works; the lead is logged instead of mailed.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


def _cfg() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or "587"),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASS", ""),
        "from": (os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "").strip(),
        "from_name": os.getenv("SMTP_FROM_NAME", "Sanas.AI — Sanas").strip(),
        "ssl": os.getenv("SMTP_SSL", "").lower() in ("1", "true", "yes"),
    }


def available() -> bool:
    c = _cfg()
    return bool(c["host"] and c["user"] and c["password"] and c["from"])


def status() -> dict:
    c = _cfg()
    return {"configured": available(), "host": c["host"] or None,
            "from": c["from"] or None}


def send(to: str, subject: str, body: str, reply_to: str | None = None) -> tuple[bool, str | None]:
    """Send one plain-text email. Returns (ok, error). Never raises."""
    if not available():
        return False, "SMTP not configured (set SMTP_* in server/.env)"
    if not to:
        return False, "no recipient"
    c = _cfg()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((c["from_name"], c["from"]))
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    try:
        if c["ssl"] or c["port"] == 465:
            with smtplib.SMTP_SSL(c["host"], c["port"], context=ssl.create_default_context(), timeout=15) as s:
                s.login(c["user"], c["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(c["host"], c["port"], timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(c["user"], c["password"])
                s.send_message(msg)
        return True, None
    except Exception as e:  # bad creds, network, blocked port — never crash the request
        return False, f"{type(e).__name__}: {e}"
