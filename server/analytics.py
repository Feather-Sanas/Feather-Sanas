"""
First-party marketing analytics: events, profiles, and chat threads.

Every browser gets a durable anonymous **profile id** (localStorage). The
front-end batches every instrumentation event (`emit()`) — page views with
UTM/referrer attribution, persona/industry picks, audio plays, ROI runs, demo
bookings, and full **chat turns** — to POST /api/events. When a visitor submits
the demo or partner form, the backend calls `identify()` and the anonymous
profile gains a name/email/company: the marketing join point.

Storage — append-only JSONL + a small JSON profile registry under SAN_DATA_DIR
(the same volume-mounted dir as the RAG store, so it survives restarts and
image rebuilds):
    events.jsonl    one event per line   {profile_id, session_id, event, ts, ...}
    profiles.json   profile_id -> {traits, first_touch, first_seen, last_seen, counts}

No database dependency; the export endpoint hands the raw JSONL to whatever
downstream tool marketing uses. Optional realtime forwarding: set
SAN_EVENTS_WEBHOOK to POST every accepted batch to a CDP/HTTP collector
(Segment HTTP source, RudderStack, Zapier, ...) fire-and-forget.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from pathlib import Path

_DIR = Path(os.getenv("SAN_DATA_DIR", str(Path(__file__).resolve().parent)))
try:
    _DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _DIR = Path(__file__).resolve().parent

EVENTS_PATH = _DIR / "events.jsonl"
PROFILES_PATH = _DIR / "profiles.json"

WEBHOOK = os.getenv("SAN_EVENTS_WEBHOOK", "").strip()

MAX_BATCH = 200          # events per POST
MAX_EVENT_BYTES = 8192   # per-event serialized cap (chat turns included)
MAX_PROFILES = int(os.getenv("SAN_MAX_PROFILES", "50000"))  # bound the registry vs bot churn
_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")

_lock = threading.Lock()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_profiles() -> dict:
    try:
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        # A transient/corrupt read must NOT clobber the registry on the next save.
        # Move the unreadable file aside (preserved for recovery) and start fresh.
        try:
            bak = PROFILES_PATH.with_name(f"profiles.json.corrupt-{int(time.time())}")
            PROFILES_PATH.replace(bak)
            print(f"[analytics] profiles.json unreadable ({e}); moved aside to {bak.name}", flush=True)
        except Exception:
            pass
        return {}


def _save_profiles(profiles: dict) -> None:
    tmp = PROFILES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(profiles, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PROFILES_PATH)


def _forward(batch: dict) -> None:
    """Fire-and-forget POST of an accepted batch to SAN_EVENTS_WEBHOOK."""
    if not WEBHOOK:
        return

    def _post():
        try:
            req = urllib.request.Request(
                WEBHOOK, data=json.dumps(batch).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            print(f"[analytics] webhook forward failed: {e}", flush=True)

    threading.Thread(target=_post, daemon=True).start()


def record_events(profile_id: str, session_id: str, events: list[dict],
                  ua: str = "", ip: str = "") -> int:
    """Append a batch of client events; update the profile's activity + first-touch
    attribution. Returns how many events were accepted."""
    if not profile_id or not isinstance(events, list):
        return 0
    now = _now_iso()
    accepted: list[dict] = []
    for ev in events[:MAX_BATCH]:
        if not isinstance(ev, dict) or not ev.get("event"):
            continue
        row = dict(ev)
        row["profile_id"] = profile_id
        row["session_id"] = session_id or row.get("session_id", "")
        row.setdefault("ts", now)
        row["server_ts"] = now
        if ua:
            row.setdefault("ua", ua[:300])
        # Enforce the per-event byte cap by SHRINKING oversized string fields, then
        # re-serialize. Never slice serialized JSON (that yields an unparseable line
        # that _iter_events would silently drop). If it still doesn't fit after
        # truncating every string, skip the event.
        if len(json.dumps(row, ensure_ascii=False)) > MAX_EVENT_BYTES:
            for k, v in list(row.items()):
                if isinstance(v, str) and len(v) > 512:
                    row[k] = v[:512] + "…"
            if len(json.dumps(row, ensure_ascii=False)) > MAX_EVENT_BYTES:
                continue  # pathological payload (non-string bloat / too many keys)
        accepted.append(row)

    if not accepted:
        return 0

    with _lock:
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            for row in accepted:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        profiles = _load_profiles()
        p = profiles.setdefault(profile_id, {"first_seen": now, "traits": {}, "counts": {}})
        p["last_seen"] = now
        counts = p.setdefault("counts", {})
        counts["events"] = counts.get("events", 0) + len(accepted)
        for row in accepted:
            if row.get("event") == "chat_turn":
                counts["chat_turns"] = counts.get("chat_turns", 0) + 1
            # first-touch attribution: first page_view's UTM/referrer sticks
            if row.get("event") == "page_view" and "first_touch" not in p:
                ft = {k: row[k] for k in (*_UTM_KEYS, "referrer", "landing") if row.get(k)}
                if ft:
                    p["first_touch"] = ft
        sessions = p.setdefault("sessions", [])
        if session_id and session_id not in sessions:
            sessions.append(session_id)
            sessions[:] = sessions[-200:]
        # Bound the registry against client-minted-UUID / bot churn: evict the
        # least-recently-seen profiles past the cap.
        if len(profiles) > MAX_PROFILES:
            for pid in sorted(profiles, key=lambda k: profiles[k].get("last_seen", ""))[:len(profiles) - MAX_PROFILES]:
                if pid != profile_id:
                    profiles.pop(pid, None)
        _save_profiles(profiles)

    _forward({"profile_id": profile_id, "session_id": session_id, "events": accepted})
    return len(accepted)


def identify(profile_id: str, traits: dict, source: str = "") -> None:
    """Merge identity traits (email/name/company/...) into a profile — called when
    a form ties a real person to the anonymous id. Non-empty values win."""
    if not profile_id or not isinstance(traits, dict):
        return
    now = _now_iso()
    clean = {k: str(v).strip()[:300] for k, v in traits.items()
             if v is not None and str(v).strip()}
    with _lock:
        profiles = _load_profiles()
        p = profiles.setdefault(profile_id, {"first_seen": now, "traits": {}, "counts": {}})
        p.setdefault("traits", {}).update(clean)
        p["last_seen"] = now
        if source:
            p["identified_via"] = source
            p.setdefault("identified_at", now)
        _save_profiles(profiles)
    record_events(profile_id, "", [{"event": "identified", "source": source,
                                    **{f"trait_{k}": v for k, v in clean.items()
                                       if k in ("email", "company")}}])


# ---- admin/read side ---------------------------------------------------------

def summary() -> dict:
    profiles = _load_profiles()
    identified = sum(1 for p in profiles.values() if p.get("traits", {}).get("email"))
    events = 0
    chat_turns = 0
    for p in profiles.values():
        events += p.get("counts", {}).get("events", 0)
        chat_turns += p.get("counts", {}).get("chat_turns", 0)
    return {"profiles": len(profiles), "identified": identified,
            "events": events, "chat_turns": chat_turns,
            "webhook_forwarding": bool(WEBHOOK),
            "store": str(EVENTS_PATH)}


def list_profiles(limit: int = 200) -> list[dict]:
    profiles = _load_profiles()
    rows = []
    for pid, p in profiles.items():
        t = p.get("traits", {})
        rows.append({
            "profile_id": pid,
            "email": t.get("email", ""),
            "name": t.get("name", ""),
            "company": t.get("company", ""),
            "first_touch": p.get("first_touch", {}),
            "first_seen": p.get("first_seen", ""),
            "last_seen": p.get("last_seen", ""),
            "events": p.get("counts", {}).get("events", 0),
            "chat_turns": p.get("counts", {}).get("chat_turns", 0),
            "sessions": len(p.get("sessions", [])),
            "identified_via": p.get("identified_via", ""),
        })
    rows.sort(key=lambda r: r.get("last_seen", ""), reverse=True)
    return rows[:limit]


def _iter_events():
    if not EVENTS_PATH.exists():
        return
    with EVENTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def profile_detail(profile_id: str, event_limit: int = 500) -> dict:
    """Full picture of one visitor: traits + raw events + chat threads
    (chat_turn events grouped by session, ordered by client ts)."""
    profiles = _load_profiles()
    p = profiles.get(profile_id, {})
    all_events = [e for e in _iter_events() if e.get("profile_id") == profile_id]
    truncated = len(all_events) > event_limit
    events = all_events[-event_limit:]
    threads: dict[str, list] = {}
    for e in events:
        if e.get("event") == "chat_turn":
            threads.setdefault(e.get("session_id", "?"), []).append(
                {"role": e.get("role", "?"), "text": e.get("text", ""),
                 "mode": e.get("mode", ""), "ts": e.get("ts", "")})
    # Overlapping flush paths (interval fetch + beacon) can arrive out of order;
    # sort each thread by client ts (stable — ties keep arrival order).
    for turns in threads.values():
        turns.sort(key=lambda u: u.get("ts") or "")
    return {"profile_id": profile_id, "profile": p, "events": events,
            "events_truncated": truncated,
            "threads": [{"session_id": sid, "turns": turns} for sid, turns in threads.items()]}


def export_bytes() -> bytes:
    """Race-free snapshot of events.jsonl for the admin export: read fully under
    the write lock so a concurrent append can't corrupt the download."""
    with _lock:
        if not EVENTS_PATH.exists():
            return b""
        return EVENTS_PATH.read_bytes()
