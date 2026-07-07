"""
Pluggable response cache for Sanas.AI's Claude replies.

The expensive part of a chat turn is the Claude call. A demo gets the same
questions over and over ("what does Sanas do?", "how low is the latency?"), so
caching the final reply keyed on the exact prompt-shaping inputs lets repeat
questions return with ZERO Claude spend.

Correctness: the key is a hash of everything that shapes the reply — model,
persona, skeptic bucket, industry, the (normalized) message history, and a
signature of the retrieved grounding sources. Identical inputs -> identical
reply, which is what makes reuse safe. A different conversation history or a
different grounding set produces a different key (a miss), so we never serve a
reply that was built from a different context.

Backend is pluggable and chosen by env at import time:
  - default: an in-process TTL cache (no dependency, no infra) — right for the
    single-host demo deploy.
  - SAN_REDIS_URL set: a Redis-backed cache (shared across instances, survives
    restarts) — the swap when you scale past one backend. redis-py is imported
    lazily; if it's missing or the server is unreachable we warn and fall back
    to memory so the request path never goes down over a cache problem.

Env:
  SAN_CACHE          on|off       enable/disable        (default on)
  SAN_CACHE_TTL      seconds      entry lifetime        (default 3600)
  SAN_CACHE_MAX      entries      in-memory cap         (default 1000)
  SAN_CACHE_VERSION  string       salt; bump to bust the whole cache when the
                                  system prompt / KB changes (default "1")
  SAN_REDIS_URL      redis://...  use Redis instead of memory (optional)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time

_ENABLED = os.getenv("SAN_CACHE", "on").strip().lower() not in ("0", "off", "false", "no", "")
_TTL = int(os.getenv("SAN_CACHE_TTL", "3600"))
_MAX = int(os.getenv("SAN_CACHE_MAX", "1000"))
_VERSION = os.getenv("SAN_CACHE_VERSION", "1")
_REDIS_URL = os.getenv("SAN_REDIS_URL", "").strip()

_WS = re.compile(r"\s+")


def enabled() -> bool:
    return _ENABLED


def ttl() -> int:
    return _TTL


def _norm(text: str) -> str:
    """Whitespace-collapsed, lowercased text — so trivial formatting differences
    in an otherwise identical question still hit the cache."""
    return _WS.sub(" ", (text or "").strip().lower())


def chat_key(model, persona, skeptic, industry, messages, sources) -> str:
    """Stable hash of everything that shapes the reply. Order-stable JSON so the
    same inputs always hash identically across processes/restarts."""
    msgs = [[m.get("role", ""), _norm(m.get("content", ""))] for m in messages]
    # Source signature: stable identifiers only (url for web, doc name for docs),
    # not the snippet text — the same grounding SET maps to the same key.
    src = sorted(
        f"{s.get('kind', 'web')}:{s.get('url') or s.get('doc_name') or s.get('title') or ''}"
        for s in (sources or [])
    )
    payload = {
        "v": _VERSION,
        "model": model or "",
        "persona": persona or "",
        "skeptic": 1 if (skeptic or 0) >= 0.5 else 0,   # matches llm.py's threshold
        "industry": industry or "",
        "msgs": msgs,
        "src": src,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "san:chat:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class _MemoryCache:
    """In-process TTL cache with a size cap. Thread-safe; lazy expiry on read."""

    def __init__(self, ttl_s: int, maxn: int):
        self._ttl = ttl_s
        self._max = maxn
        self._d: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        now = time.monotonic()
        with self._lock:
            ent = self._d.get(key)
            if not ent:
                return None
            exp, val = ent
            if exp < now:
                self._d.pop(key, None)
                return None
            return val

    def set(self, key, value):
        now = time.monotonic()
        with self._lock:
            if len(self._d) >= self._max and key not in self._d:
                # prune expired first, then evict the soonest-to-expire entry
                for k, (exp, _) in list(self._d.items()):
                    if exp < now:
                        self._d.pop(k, None)
                if len(self._d) >= self._max:
                    self._d.pop(min(self._d, key=lambda k: self._d[k][0]), None)
            self._d[key] = (now + self._ttl, value)

    def info(self):
        return {"backend": "memory", "entries": len(self._d), "ttl_s": self._ttl, "max": self._max}


class _RedisCache:
    """Redis-backed cache. Same interface as _MemoryCache. Every call is wrapped
    so a Redis hiccup degrades to a miss rather than failing the request."""

    def __init__(self, url: str, ttl_s: int):
        import redis  # lazy: only imported when SAN_REDIS_URL is configured
        self._ttl = ttl_s
        self._url = url
        self._r = redis.Redis.from_url(url, decode_responses=True,
                                       socket_timeout=2, socket_connect_timeout=2)
        self._r.ping()  # fail fast at construction so we can fall back to memory

    def get(self, key):
        try:
            return self._r.get(key)
        except Exception:
            return None

    def set(self, key, value):
        try:
            self._r.setex(key, self._ttl, value)
        except Exception:
            pass

    def info(self):
        return {"backend": "redis", "url": self._url, "ttl_s": self._ttl}


def _build():
    if _REDIS_URL:
        try:
            c = _RedisCache(_REDIS_URL, _TTL)
            print(f"[cache] response cache: redis ({_REDIS_URL})", flush=True)
            return c
        except Exception as e:
            print(f"[cache] SAN_REDIS_URL set but Redis unavailable ({e}); "
                  f"falling back to in-memory cache", flush=True)
    return _MemoryCache(_TTL, _MAX)


_cache = _build() if _ENABLED else None


def get(key):
    if not (_ENABLED and _cache and key):
        return None
    return _cache.get(key)


def set(key, value):  # noqa: A001 — module-level api, not the builtin
    if not (_ENABLED and _cache and key and value):
        return
    _cache.set(key, value)


def info() -> dict:
    if not _ENABLED:
        return {"enabled": False}
    d = {"enabled": True}
    d.update(_cache.info())
    return d
