"""
Lightweight per-IP rate limiter for the expensive endpoints — the Claude chat
path and the audio / ASR / RAG-upload compute paths. A single client or a bot
shouldn't be able to run up the Claude bill or saturate the box.

Fixed-window counter, in-process (right for the single-host demo). A
multi-instance production deploy would back the same seam with Redis so the
window is shared across backends; the dependency signature stays identical.

Env:
  SAN_RATE_LIMIT    requests per window per IP   (default 60; 0/off disables)
  SAN_RATE_WINDOW   window length in seconds      (default 60)

Wire it onto a route with  Depends(rate_limit)  — it raises HTTP 429 (with a
Retry-After header) when an IP exceeds the limit. Twilio webhooks and the
static / health routes are intentionally NOT rate-limited.
"""
from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException, Request

_RAW = os.getenv("SAN_RATE_LIMIT", "60").strip().lower()
_ENABLED = _RAW not in ("0", "off", "false", "no", "")
_LIMIT = int(_RAW) if _RAW.isdigit() else 60
_WINDOW = int(os.getenv("SAN_RATE_WINDOW", "60"))

_buckets: dict[str, list] = {}   # ip -> [window_start_monotonic, count]
_lock = threading.Lock()
_last_prune = [0.0]


def client_ip(request: Request) -> str:
    """Real client IP behind Caddy / an ALB: first hop of X-Forwarded-For, else
    the direct peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow(ip: str):
    now = time.monotonic()
    with _lock:
        # prune stale buckets occasionally so memory stays bounded under churn
        if now - _last_prune[0] > _WINDOW:
            for k, (start, _) in list(_buckets.items()):
                if now - start > _WINDOW:
                    _buckets.pop(k, None)
            _last_prune[0] = now
        ent = _buckets.get(ip)
        if ent is None or now - ent[0] >= _WINDOW:
            _buckets[ip] = [now, 1]
            return True, 0
        ent[1] += 1
        if ent[1] > _LIMIT:
            return False, max(1, int(_WINDOW - (now - ent[0])))
        return True, 0


def rate_limit(request: Request) -> None:
    """FastAPI dependency. 429 (with Retry-After) when the caller exceeds the
    per-IP window. No-op when disabled (SAN_RATE_LIMIT=0/off)."""
    if not _ENABLED:
        return
    ok, retry = _allow(client_ip(request))
    if not ok:
        raise HTTPException(status_code=429, detail="Too many requests — slow down.",
                            headers={"Retry-After": str(retry)})


# --- Separate, higher-cap bucket for the analytics ingest endpoint -------------
# /api/events is high-frequency (background flushes) but cheap; keep it OUT of the
# shared expensive-endpoint budget so it can't 429 chat for users behind one NAT.
_EVT_RAW = os.getenv("SAN_EVENTS_RATE_LIMIT", "240").strip().lower()
_EVT_ENABLED = _EVT_RAW not in ("0", "off", "false", "no", "")
_EVT_LIMIT = int(_EVT_RAW) if _EVT_RAW.isdigit() else 240
_evt_buckets: dict[str, list] = {}
_evt_last_prune = [0.0]


def _allow_evt(ip: str):
    now = time.monotonic()
    with _lock:
        if now - _evt_last_prune[0] > _WINDOW:
            for k, (start, _) in list(_evt_buckets.items()):
                if now - start > _WINDOW:
                    _evt_buckets.pop(k, None)
            _evt_last_prune[0] = now
        ent = _evt_buckets.get(ip)
        if ent is None or now - ent[0] >= _WINDOW:
            _evt_buckets[ip] = [now, 1]
            return True, 0
        ent[1] += 1
        if ent[1] > _EVT_LIMIT:
            return False, max(1, int(_WINDOW - (now - ent[0])))
        return True, 0


def events_rate_limit(request: Request) -> None:
    """FastAPI dependency for /api/events — its own per-IP window (SAN_EVENTS_RATE_LIMIT)."""
    if not _EVT_ENABLED:
        return
    ok, retry = _allow_evt(client_ip(request))
    if not ok:
        raise HTTPException(status_code=429, detail="Too many requests — slow down.",
                            headers={"Retry-After": str(retry)})


def info() -> dict:
    return {"enabled": _ENABLED, "limit": _LIMIT, "window_s": _WINDOW,
            "events_limit": _EVT_LIMIT if _EVT_ENABLED else 0}
