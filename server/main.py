"""
San backend — orchestrator surface for the Sanas Speech AI consultant.

Endpoints:
  GET  /api/health         -> SDK init status, mode (real|unavailable), active processors
  GET  /api/models         -> available models + sample rates
  POST /api/process        -> multipart audio upload -> Sanas-processed WAV
                              (header X-Sanas-* carries the ingress quality probe)
Static:
  /                        -> serves the San front-end (index.html, app.js, styles.css)

Credentials live ONLY here (env vars), never in the browser.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel


def _load_dotenv() -> None:
    """Load server/.env into the environment for native runs. A non-empty var
    already in the environment wins (so Docker's env_file still takes precedence),
    but a .env value DOES override a missing or empty/blank existing var — otherwise
    an empty `ANTHROPIC_API_KEY=` left in the shell would silently mask the key.
    Must run before importing llm / sanas_client, which read env at import time."""
    p = Path(__file__).resolve().parent / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and not os.environ.get(k, "").strip():
            os.environ[k] = v


_load_dotenv()

import analytics  # noqa: E402  (after dotenv load; reads SAN_DATA_DIR at import)
import asr  # noqa: E402
import doc_index  # noqa: E402
import llm  # noqa: E402
import mailer  # noqa: E402
import ratelimit  # noqa: E402  (per-IP rate limit; reads env at import)
import response_cache  # noqa: E402  (Claude reply cache; reads env at import)
import webindex  # noqa: E402
from ratelimit import rate_limit, events_rate_limit  # noqa: E402
from sanas_client import client, MODEL_SAMPLE_RATES  # noqa: E402

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # generous cap; spec limits clips to ~2 min
# In Docker the front-end lives in a dedicated dir (WEB_DIR env); for local dev
# it sits one level up from server/ (the project root).
WEB_DIR = Path(os.getenv("WEB_DIR", Path(__file__).resolve().parent.parent))

app = FastAPI(title="San — Sanas SDK orchestrator", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # Connect to the SIP endpoint off the startup path so the server binds and
    # serves immediately; health reports mode='unavailable' until the SDK connects.
    threading.Thread(target=client.initialize, daemon=True).start()
    # Pre-warm the Whisper model so the first in-call "done" transcription is fast
    # (cold load is ~5s — too slow to catch a spoken command on a live call).
    if asr.available():
        threading.Thread(target=lambda: asr.transcribe(np.zeros(8000, dtype=np.int16), 8000),
                         daemon=True).start()


@app.on_event("shutdown")
def _shutdown() -> None:
    client.shutdown()


@app.get("/api/health")
def health() -> JSONResponse:
    h = client.health()
    h["llm_available"] = llm.available()
    h["llm_model"] = llm.MODEL if llm.available() else None
    h["asr_available"] = asr.available()
    h["asr_model"] = asr.MODEL_NAME if asr.available() else None
    h["web_index"] = webindex.count()
    h["rag_docs"] = doc_index.count()
    h["rag_chunks"] = doc_index.chunk_count()
    h["response_cache"] = response_cache.info()
    h["rate_limit"] = ratelimit.info()
    # analytics totals/paths are admin-only (GET /api/analytics/summary) — not leaked here
    return JSONResponse(h)


def _last_user(msgs: list[dict]) -> str:
    for m in reversed(msgs):
        if m["role"] == "user":
            return m["content"]
    return ""


_SUPPORT_KW = (
    "install", "set up", "setup", "configure", "config", "integrat", "troubleshoot",
    "not working", "doesn't work", "can't", "cannot", "can not", "error", "crash",
    " fix", "reset", "password", "log in", "login", "sign in", "sso", "dialer",
    "microphone", " mic ", "headset", "device", "audio", "echo", "uninstall",
    "update", "activate", "activation", "portal", "how do i", "how to", "step by step",
    "settings", "setting", "no sound", "can i hear", "hear me", "hear the",
)


def _prefer(persona: str | None, query: str = "") -> str | None:
    """Bias retrieval toward a section. Data scientists get grounded in the science
    articles; support/how-to questions get grounded in the help center."""
    if persona == "data_scientist":
        return "/science"
    if persona == "help":
        return "help.sanas.ai"
    if persona == "partner":
        return "/partners"
    q = (query or "").lower()
    if any(k in q for k in _SUPPORT_KW):
        return "help.sanas.ai"
    return None


def _retrieve(persona: str | None, q: str, industry: str | None = None, k: int = 3) -> list[dict]:
    """Ground a chat turn in BOTH corpora: the user's uploaded documents (RAG)
    and the crawled sanas.ai site. Uploaded-doc hits lead — they're the user's
    own material — then site pages fill the rest. A selected industry biases the
    site retrieval toward that vertical's page. Each item keeps a 'kind'
    ('doc' | 'web') so the LLM and UI can label the source correctly."""
    ind_pref = _INDUSTRY_PREFER.get(industry)
    prefer = ind_pref or _prefer(persona, q)
    docs = doc_index.search(q, k=2) if doc_index.count() else []
    web = webindex.search(q, k=k, prefer=prefer)
    # When an industry is selected, pin its landing page AND its customer story into
    # context (term-matching alone may miss them) so answers ground in the vertical
    # and can cite the matching case study.
    pinned: list[dict] = []
    if ind_pref:
        page = webindex.by_url(ind_pref)
        if page:
            pinned.append(page)
    story = _INDUSTRY_STORIES.get(industry)
    if story:
        pinned.append(dict(story))
    if pinned:
        urls = {p["url"] for p in pinned}
        web = pinned + [w for w in web if w["url"] not in urls]
    for w in web:
        w.setdefault("kind", "web")
    return (docs + web)[:k + len(docs) + len(pinned)]


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    messages: list[ChatTurn]
    persona: str | None = None
    skeptic: float = 0.0
    industry: str | None = None


# Industry verticals Sanas publishes (+ Telecom). The value biases retrieval toward
# that industry's sanas.ai page; the label is passed to the LLM as vertical context.
_INDUSTRY_PREFER = {
    "healthcare": "/healthcare", "financial-services": "/financial-services",
    "retail": "/retail", "travel": "/travel", "telecom": None,
}
_INDUSTRY_LABEL = {
    "healthcare": "Healthcare", "financial-services": "Financial Services",
    "retail": "Retail", "travel": "Travel & Hospitality", "telecom": "Telecom",
}
# Real sanas.ai customer stories per vertical — pinned into retrieval when that
# industry is selected so Claude can cite the matching case study (the individual
# story pages aren't in the crawled index).
_INDUSTRY_STORIES = {
    "healthcare": {"title": "Customer story — Healthcare Revenue Cycle Leader",
                   "url": "https://www.sanas.ai/customer-stories/healthcare-revenue-cycle",
                   "snippet": "How a healthcare revenue cycle leader improved clarity and patient experience with Sanas."},
    "financial-services": {"title": "Customer story — Fortune 50 Global Financial Services Leader",
                   "url": "https://www.sanas.ai/customer-stories/global-financial-services",
                   "snippet": "A Fortune 50 financial-services leader strengthened trust, clarity, and compliance on every call with Sanas."},
    "retail": {"title": "Customer story — Food Delivery Platform",
                   "url": "https://www.sanas.ai/customer-stories/food-delivery-platform",
                   "snippet": "A food-delivery platform boosted CSAT and efficiency with Sanas Accent Translation."},
    "travel": {"title": "Customer story — Wyndham Group",
                   "url": "https://www.sanas.ai/customer-stories/wyndham-hotels",
                   "snippet": "Wyndham Group saw a 50% increase in sales with Sanas."},
    "telecom": {"title": "Customer story — Cable & Internet Provider",
                   "url": "https://www.sanas.ai/customer-stories/cable-and-internet-provider",
                   "snippet": "A cable & internet provider enhanced outbound sales conversions with Sanas Accent Translation."},
}


@app.post("/api/chat")
def chat(req: ChatReq, _rl: None = Depends(rate_limit)) -> JSONResponse:
    """Generate San's reply via Claude. Returns mode='fallback' (text=None)
    when no API key is configured, so the client uses its rule-based engine.
    A repeat question (same persona/skeptic/industry/history/grounding) is served
    from the response cache with no Claude call."""
    msgs = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    # API requires the history to start with a user turn and be non-empty
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages")
    _q = _last_user(msgs)
    sources = _retrieve(req.persona, _q, req.industry)
    _industry = _INDUSTRY_LABEL.get(req.industry)
    src_out = [{"title": s["title"], "url": s["url"], "kind": s.get("kind", "web")}
               for s in sources]
    # Response cache: identical prompt-shaping inputs -> reuse the reply (no API call).
    ckey = (response_cache.chat_key(llm.MODEL, req.persona, req.skeptic, _industry, msgs, sources)
            if (response_cache.enabled() and llm.available()) else None)
    cached = response_cache.get(ckey) if ckey else None
    if cached is not None:
        return JSONResponse({"text": cached, "mode": "llm", "model": llm.MODEL,
                             "cached": True, "sources": src_out})
    text = llm.chat(msgs, req.persona, req.skeptic, context=sources, industry=_industry)
    if text and ckey:
        response_cache.set(ckey, text)
    return JSONResponse({
        "text": text,
        "mode": "llm" if text else "fallback",
        "model": llm.MODEL if text else None,
        "cached": False,
        "sources": src_out,
    })


@app.post("/api/chat/stream")
def chat_stream(req: ChatReq, _rl: None = Depends(rate_limit)):
    """Stream San's reply token-by-token as plain-text chunks. The X-San-Mode
    response header is 'llm' when streaming real content, 'fallback' (empty body)
    when no key is configured — the client then uses its rule-based reply. A cache
    hit (X-San-Cached: 1) replays the stored reply as a stream so the UX is
    identical; a miss accumulates the streamed text and stores it on completion."""
    msgs = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages")
    _q = _last_user(msgs)
    sources = _retrieve(req.persona, _q, req.industry)
    src_hdr = json.dumps([{"title": s["title"], "url": s["url"], "kind": s.get("kind", "web")}
                          for s in sources])  # ASCII, one line
    if not llm.available():
        return Response(content=b"", media_type="text/plain",
                        headers={"X-San-Mode": "fallback", "X-San-Sources": src_hdr,
                                 "Access-Control-Expose-Headers": "*"})

    _industry = _INDUSTRY_LABEL.get(req.industry)
    base_headers = {"X-San-Mode": "llm", "X-Sanas-Model": llm.MODEL,
                    "X-San-Sources": src_hdr, "Access-Control-Expose-Headers": "*",
                    "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    ckey = (response_cache.chat_key(llm.MODEL, req.persona, req.skeptic, _industry, msgs, sources)
            if response_cache.enabled() else None)
    cached = response_cache.get(ckey) if ckey else None
    if cached is not None:
        def gen_cached():
            # replay the stored reply in small chunks so the client renders it
            # progressively, exactly like a live stream
            for i in range(0, len(cached), 24):
                yield cached[i:i + 24]
        return StreamingResponse(gen_cached(), media_type="text/plain; charset=utf-8",
                                 headers={**base_headers, "X-San-Cached": "1"})

    def gen():
        parts: list[str] = []
        for delta in llm.chat_stream(msgs, req.persona, req.skeptic, context=sources, industry=_industry):
            parts.append(delta)
            yield delta
        full = "".join(parts).strip()
        if full and ckey:
            response_cache.set(ckey, full)

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8", headers=base_headers)


# Friendly metadata for the playground. SE + NC families are real SDK models;
# Accent / Language Translation are Sanas product capabilities not exposed as
# models in this SDK build (marked unavailable so the UI is honest).
MODEL_META = {
    "SE2.2":            {"label": "Speech Enhancement — Ultra",        "category": "Speech Enhancement"},
    "SE2.1":            {"label": "Speech Enhancement — Standard",     "category": "Speech Enhancement"},
    "VI_G_NC3.0":       {"label": "Noise Cancellation — Voice Isolation", "category": "Noise Cancellation"},
    "AGENTIC_VI_G_NC":  {"label": "Agentic NC — Voice Isolation",      "category": "Noise Cancellation"},
    "AGENTIC_ST_NC":    {"label": "Agentic NC — Standard",             "category": "Noise Cancellation"},
    "AGENTIC_VI_GT_NC": {"label": "Agentic NC — Telephony (8 kHz)",    "category": "Noise Cancellation"},
}


@app.get("/api/models")
def models() -> JSONResponse:
    model_list = [
        {"name": name, "sample_rate": sr,
         "label": MODEL_META.get(name, {}).get("label", name),
         "category": MODEL_META.get(name, {}).get("category", "Other"),
         "available": True}
        for name, sr in MODEL_SAMPLE_RATES.items()
    ]
    features = [
        {"key": "speech_enhancement", "label": "Speech Enhancement", "available": True,
         "models": [m["name"] for m in model_list if m["category"] == "Speech Enhancement"]},
        {"key": "noise_cancellation", "label": "Noise Cancellation", "available": True,
         "models": [m["name"] for m in model_list if m["category"] == "Noise Cancellation"]},
        {"key": "accent_translation", "label": "Accent Translation", "available": False, "models": [],
         "note": "Sanas product capability — not exposed as a model in this SDK build."},
        {"key": "language_translation", "label": "Language Translation", "available": False, "models": [],
         "note": "Sanas product capability — not exposed as a model in this SDK build.",
         "languages": {"source": ["English", "French"], "target": ["Spanish", "English", "French"]}},
    ]
    return JSONResponse({"models": model_list, "features": features,
                         "default": client.model, "sanas_mode": client.mode})


def _decode_to_pcm(raw: bytes, target_sr: int) -> np.ndarray:
    """Use ffmpeg to convert any input audio to mono s16le PCM at target_sr."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-ac", "1", "-ar", str(target_sr),
         "-f", "s16le", "pipe:1"],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=415,
                            detail=f"Could not decode audio: {proc.stderr.decode()[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.int16).copy()


def _encode_wav(samples: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()


def _ingress_probe(samples: np.ndarray, sr: int) -> dict:
    """Same probe the speech engine emits in production (SNR/clip/silence/etc)."""
    x = samples.astype(np.float32) / 32768.0
    if len(x) == 0:
        raise HTTPException(status_code=400, detail="Empty audio")
    peak = float(np.max(np.abs(x)))
    clip_rate = float(np.mean(np.abs(x) > 0.98)) * 100.0
    rms = float(np.sqrt(np.mean(x ** 2)) + 1e-9)
    # crude SNR: ratio of speech-band energy to quietest 10% (noise floor)
    frame = max(1, sr // 50)
    energies = np.array([np.sqrt(np.mean(x[i:i + frame] ** 2) + 1e-12)
                         for i in range(0, len(x) - frame, frame)]) if len(x) > frame else np.array([rms])
    noise_floor = float(np.percentile(energies, 10) + 1e-9)
    snr_db = float(20.0 * np.log10(rms / noise_floor))
    silence_ratio = float(np.mean(energies < noise_floor * 1.5)) * 100.0
    vad_conf = float(np.clip(1.0 - silence_ratio / 100.0, 0.0, 1.0))
    return {
        "snr_db": round(snr_db, 1),
        "clip_rate_pct": round(clip_rate, 1),
        "silence_ratio_pct": round(silence_ratio, 1),
        "sample_rate": sr,
        "peak": round(peak, 3),
        "vad_confidence": round(vad_conf, 2),
        "duration_s": round(len(x) / sr, 1),
    }


@app.post("/api/process")
async def process(file: UploadFile = File(...), model: str | None = None,
                  _rl: None = Depends(rate_limit)):
    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    # No mock: without the real engine we return no audio, not a synthetic stand-in.
    if not client.available():
        raise HTTPException(status_code=503,
                            detail="Sanas engine unavailable — the real-time SDK is not connected.")

    model = model or client.model
    sr = MODEL_SAMPLE_RATES.get(model, client.sample_rate)

    # ffmpeg decode (subprocess) and the SDK's real-time-paced process() are BLOCKING
    # and can run for the full clip duration (up to SAN_MAX_CLIP_S). Run them on a
    # worker thread, never on the event loop — otherwise a single clip stalls every
    # other request (chat, the live-mic WebSocket, health).
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    samples = await loop.run_in_executor(None, _decode_to_pcm, raw, sr)
    # The real engine runs in real time, so wall-clock ≈ clip duration. Cap the
    # clip so an upload can't hang the request for minutes (SAN_MAX_CLIP_S).
    max_clip_s = float(os.getenv("SAN_MAX_CLIP_S", "30"))
    max_samples = int(max_clip_s * sr)
    truncated = len(samples) > max_samples
    if truncated:
        samples = samples[:max_samples]
    t_ingress = time.perf_counter()
    probe = _ingress_probe(samples, sr)
    processed = await loop.run_in_executor(None, client.process, samples, sr, model)
    t_inference = time.perf_counter()
    wav = _encode_wav(processed, sr)

    headers = {
        "X-Sanas-Mode": client.mode,
        "X-Sanas-Model": model,
        "X-Sanas-Sample-Rate": str(sr),
        "X-Sanas-SNR-dB": str(probe["snr_db"]),
        "X-Sanas-Clip-Rate": str(probe["clip_rate_pct"]),
        "X-Sanas-Silence-Ratio": str(probe["silence_ratio_pct"]),
        "X-Sanas-VAD": str(probe["vad_confidence"]),
        "X-Sanas-Duration": str(probe["duration_s"]),
        "X-Sanas-Truncated": "1" if truncated else "0",
        "X-Sanas-Clip-Limit-S": str(max_clip_s),
        # layer timings (ms) for the developer 8-layer trace
        "X-Sanas-T-Ingress": str(round((t_ingress - t0) * 1000, 1)),
        "X-Sanas-T-Inference": str(round((t_inference - t_ingress) * 1000, 1)),
        "Access-Control-Expose-Headers": "*",
    }
    return Response(content=wav, media_type="audio/wav", headers=headers)


# ---- Admin auth: gate knowledge-base (RAG) upload/management behind a login ----
# RAG_ADMIN_PASSWORD lives only in server/.env. If unset, admin login is "not
# configured" and the upload/manage endpoints are locked. Login issues an in-memory
# bearer token (cleared on restart); chat-time RETRIEVAL stays open to everyone.
import hmac as _hmac
import secrets as _secrets

RAG_ADMIN_PASSWORD = os.getenv("RAG_ADMIN_PASSWORD", "")
_ADMIN_TOKENS: set[str] = set()


def _admin_configured() -> bool:
    return bool(RAG_ADMIN_PASSWORD)


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    """Dependency: 401 unless a valid admin token is presented. 503 if no admin
    password is configured on the server (so the feature is locked, not open)."""
    if not _admin_configured():
        raise HTTPException(status_code=503, detail="Admin login is not configured on this server.")
    if not x_admin_token or x_admin_token not in _ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Admin login required.")


class AdminLogin(BaseModel):
    password: str = ""


@app.get("/api/admin/status")
def admin_status() -> JSONResponse:
    return JSONResponse({"configured": _admin_configured()})


@app.post("/api/admin/login")
def admin_login(req: AdminLogin) -> JSONResponse:
    if not _admin_configured():
        return JSONResponse({"ok": False, "configured": False,
                             "detail": "Admin login is not configured. Set RAG_ADMIN_PASSWORD in server/.env."})
    if not _hmac.compare_digest(req.password or "", RAG_ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    token = _secrets.token_urlsafe(24)
    _ADMIN_TOKENS.add(token)
    print("[admin] login ok", flush=True)
    return JSONResponse({"ok": True, "token": token})


@app.post("/api/admin/logout")
def admin_logout(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> JSONResponse:
    if x_admin_token:
        _ADMIN_TOKENS.discard(x_admin_token)
    return JSONResponse({"ok": True})


_RAG_EXTS = (".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm", ".text")


@app.post("/api/rag/upload")
async def rag_upload(file: UploadFile = File(...), _: None = Depends(require_admin),
                     __: None = Depends(rate_limit)) -> JSONResponse:
    """Ingest an unstructured document (PDF / DOCX / TXT / MD) so Sanas.AI can answer
    grounded in it. Parsed, chunked, and persisted to disk; shared across sessions.
    Admin-only (knowledge-base management); chat retrieval over the docs stays open."""
    name = file.filename or ""
    if not name.lower().endswith(_RAG_EXTS):
        raise HTTPException(status_code=415,
                            detail="Unsupported type. Upload PDF, DOCX, TXT, or MD.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        # parsing (pypdf/python-docx) can be slow on a large file — off the event loop
        info = await asyncio.get_running_loop().run_in_executor(None, doc_index.ingest, name, raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse document: {e}")
    return JSONResponse({"ok": True, **info})


@app.get("/api/rag/docs")
def rag_docs(_: None = Depends(require_admin)) -> JSONResponse:
    return JSONResponse({"docs": doc_index.list_docs(), "chunks": doc_index.chunk_count()})


@app.post("/api/rag/clear")
def rag_clear(_: None = Depends(require_admin)) -> JSONResponse:
    return JSONResponse({"ok": True, "removed": doc_index.clear()})


# ---- Marketing analytics: event ingestion (public) + reporting (admin) --------
_EVENTS_BODY_CAP = 256 * 1024   # public endpoint — bound the write, not just the rate

@app.post("/api/events")
async def ingest_events(request: Request, _rl: None = Depends(events_rate_limit)) -> JSONResponse:
    """Batched first-party event capture from the front-end (fetch or sendBeacon).
    Body: {profile_id, session_id, events: [{event, ts, ...props}]}. Events land in
    events.jsonl under SAN_DATA_DIR, tied to the visitor's durable profile id."""
    raw = await request.body()
    if len(raw) > _EVENTS_BODY_CAP:   # cap bytes, not just requests (public endpoint)
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    events = body.get("events") or []
    if not isinstance(events, list) or len(events) > analytics.MAX_BATCH:
        raise HTTPException(status_code=400, detail="events must be a list (max %d)" % analytics.MAX_BATCH)
    # Disk I/O + the global profile lock run OFF the event loop so a busy ingest
    # can never stall chat/websocket/health.
    loop = asyncio.get_running_loop()
    n = await loop.run_in_executor(
        None, analytics.record_events,
        str(body.get("profile_id") or "")[:64], str(body.get("session_id") or "")[:64],
        events, request.headers.get("user-agent", ""))
    return JSONResponse({"ok": True, "accepted": n})


@app.get("/api/analytics/summary")
def analytics_summary(_: None = Depends(require_admin)) -> JSONResponse:
    return JSONResponse(analytics.summary())


@app.get("/api/analytics/profiles")
def analytics_profiles(_: None = Depends(require_admin)) -> JSONResponse:
    return JSONResponse({"profiles": analytics.list_profiles()})


@app.get("/api/analytics/profile/{profile_id}")
def analytics_profile(profile_id: str, _: None = Depends(require_admin)) -> JSONResponse:
    return JSONResponse(analytics.profile_detail(profile_id))


@app.get("/api/analytics/export")
def analytics_export(_: None = Depends(require_admin)):
    """Raw events.jsonl download — one JSON event per line, ready for a warehouse,
    spreadsheet import, or a CDP batch upload. Snapshotted under the write lock so a
    concurrent append can't race the response's Content-Length."""
    return Response(content=analytics.export_bytes(), media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=events.jsonl"})


# ---- "Book a demo / More information" — intake + email + Google booking link ----
DEMO_NOTIFY_EMAIL = os.getenv("DEMO_NOTIFY_EMAIL", "chris.featherstone@sanas.ai")
BOOKING_URL = os.getenv("BOOKING_URL", "https://calendar.app.google/BzRcDMQAKtHvRJfs8")
DEMO_LEADS: list[dict] = []
import re as _re  # noqa: E402
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DemoRequest(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    company: str = ""
    job_title: str = ""
    phone: str = ""
    company_size: str = ""
    message: str = ""
    profile_id: str = ""   # visitor's analytics profile — ties the lead to their event history


_EMBED_CACHE: dict = {"done": False, "url": None}


def _booking_embed_url() -> str | None:
    """Resolve BOOKING_URL (a calendar.app.google short link) to Google's embeddable
    Appointment Scheduling URL — `/calendar/appointments/schedules/<id>?gv=true`, the
    only variant that omits X-Frame-Options so it can render in an iframe. Cached;
    returns None if it can't be resolved (the UI then falls back to the plain link)."""
    if _EMBED_CACHE["done"]:
        return _EMBED_CACHE["url"]
    _EMBED_CACHE["done"] = True
    url = None
    try:
        m = _re.search(r"/appointments/schedules/([^/?#]+)", BOOKING_URL)
        if not m:                                  # short link → follow redirects to the full URL
            import requests
            final = requests.get(BOOKING_URL, allow_redirects=True, timeout=8).url
            m = _re.search(r"/appointments/schedules/([^/?#]+)", final)
        if m:
            url = f"https://calendar.google.com/calendar/appointments/schedules/{m.group(1)}?gv=true"
    except Exception as e:
        print(f"[demo-book] could not resolve booking embed url: {e}", flush=True)
        url = None
    _EMBED_CACHE["url"] = url
    return url


@app.get("/api/demo/config")
def demo_config() -> JSONResponse:
    return JSONResponse({"booking_url": BOOKING_URL, "embed_url": _booking_embed_url(),
                         "email_configured": mailer.available()})


@app.post("/api/demo/book")
def demo_book(req: DemoRequest) -> JSONResponse:
    """Mimics the sanas.ai/book-demo intake: capture the lead, email it to the
    internal owner + send the contact a confirmation with the Google booking link,
    then return that link so the UI can route them to pick a time."""
    email = (req.email or "").strip()
    name = " ".join(p for p in [req.first_name.strip(), req.last_name.strip()] if p) or "(no name)"
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="A valid work email is required.")

    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    fields = [("Name", name), ("Work email", email), ("Company", req.company),
              ("Job title", req.job_title), ("Phone", req.phone),
              ("Company size", req.company_size), ("Looking to solve", req.message)]
    detail = "\n".join(f"{k}: {v}" for k, v in fields if v)
    lead = {k.lower().replace(" ", "_"): v for k, v in fields}
    lead["received"] = ts
    DEMO_LEADS.append(lead)
    print(f"[demo-book] lead from {name} <{email}> ({req.company or 'n/a'})", flush=True)
    # Identity resolution: the anonymous analytics profile becomes a known lead.
    if req.profile_id:
        analytics.identify(req.profile_id.strip()[:64],
                           {"email": email, "name": name, "company": req.company,
                            "job_title": req.job_title, "phone": req.phone,
                            "company_size": req.company_size},
                           source="demo_form")

    # 1) internal notification to the owner (reply-To the contact so a reply reaches them)
    notify_body = (f"New demo request from Sanas.AI (More Information).\n\n{detail}\n\n"
                   f"Received: {ts}\nBooking link sent to the contact: {BOOKING_URL}\n")
    notify_ok, notify_err = mailer.send(DEMO_NOTIFY_EMAIL,
                                        f"New demo request — {name}" + (f", {req.company}" if req.company else ""),
                                        notify_body, reply_to=email)
    # 2) confirmation to the contact with the scheduling link
    first = req.first_name.strip() or "there"
    confirm_body = (f"Hi {first},\n\nThanks for your interest in Sanas. Pick a time that works for you "
                    f"and we'll walk you through it live:\n\n{BOOKING_URL}\n\n"
                    f"We've logged your details:\n{detail}\n\n— The Sanas team\n")
    contact_ok, contact_err = mailer.send(email, "Your Sanas demo — pick a time", confirm_body)

    if notify_err:
        print(f"[demo-book] notify email not sent: {notify_err}", flush=True)
    if contact_err:
        print(f"[demo-book] contact email not sent: {contact_err}", flush=True)

    return JSONResponse({
        "ok": True,
        "booking_url": BOOKING_URL,
        "embed_url": _booking_embed_url(),
        "email_configured": mailer.available(),
        "emailed": {"notify": notify_ok, "contact": contact_ok},
    })


PARTNERS_URL = "https://www.sanas.ai/partners"
PARTNER_LEADS: list[dict] = []


class PartnerRequest(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    company: str = ""
    partnership_type: str = ""
    region: str = ""
    website: str = ""
    message: str = ""
    profile_id: str = ""   # visitor's analytics profile — ties the application to their event history


@app.post("/api/partner/apply")
def partner_apply(req: PartnerRequest) -> JSONResponse:
    """Partner application (mirrors sanas.ai/partner-form): capture + email to the
    partnerships owner + confirm to the applicant. Degrades to logged when SMTP unset."""
    email = (req.email or "").strip()
    name = " ".join(p for p in [req.first_name.strip(), req.last_name.strip()] if p) or "(no name)"
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="A valid work email is required.")
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    fields = [("Name", name), ("Work email", email), ("Company", req.company),
              ("Partnership type", req.partnership_type), ("Region", req.region),
              ("Website", req.website), ("About", req.message)]
    detail = "\n".join(f"{k}: {v}" for k, v in fields if v)
    PARTNER_LEADS.append({k.lower().replace(" ", "_"): v for k, v in fields} | {"received": ts})
    print(f"[partner] application from {name} <{email}> ({req.company or 'n/a'}, {req.partnership_type or 'n/a'})", flush=True)
    if req.profile_id:
        analytics.identify(req.profile_id.strip()[:64],
                           {"email": email, "name": name, "company": req.company,
                            "partnership_type": req.partnership_type, "region": req.region,
                            "website": req.website},
                           source="partner_form")

    notify_ok, notify_err = mailer.send(
        DEMO_NOTIFY_EMAIL, f"New partner application — {name}" + (f", {req.company}" if req.company else ""),
        f"New partner application from Sanas.AI.\n\n{detail}\n\nReceived: {ts}\nPrograms: {PARTNERS_URL}\n",
        reply_to=email)
    first = req.first_name.strip() or "there"
    contact_ok, _ = mailer.send(
        email, "Thanks for your interest in the Sanas Partner Program",
        f"Hi {first},\n\nThanks for your interest in partnering with Sanas. Our partnerships team has your "
        f"details and will be in touch. More on the programs: {PARTNERS_URL}\n\nWe've logged:\n{detail}\n\n— The Sanas team\n")
    if notify_err:
        print(f"[partner] notify email not sent: {notify_err}", flush=True)
    return JSONResponse({"ok": True, "partners_url": PARTNERS_URL,
                         "email_configured": mailer.available(),
                         "emailed": {"notify": notify_ok, "contact": contact_ok}})


@app.post("/api/asr")
async def asr_compare(
    before: UploadFile = File(...),
    after: UploadFile = File(...),
    reference_audio: UploadFile | None = File(None),
    _rl: None = Depends(rate_limit),
):
    """Transcribe before/after audio with a real ASR (faster-whisper).
    If a clean `reference_audio` is supplied (curated scenarios send the clean
    voice bed), compute true WER for each and the WER delta; otherwise report the
    recognition-confidence delta (uploads have no clean reference)."""
    if not asr.available():
        return JSONResponse({"available": False,
                             "detail": "faster-whisper not installed on this backend"})

    sr = 16000  # Whisper operates at 16 kHz
    loop = asyncio.get_running_loop()

    async def tx(f: UploadFile):
        raw = await f.read()
        if not raw:
            raise HTTPException(status_code=400, detail="empty audio")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="file too large")
        # ffmpeg decode + Whisper are blocking — keep them off the event loop so an
        # ASR run can't stall the event loop and block other requests.
        pcm = await loop.run_in_executor(None, _decode_to_pcm, raw, sr)
        return await loop.run_in_executor(None, asr.transcribe, pcm, sr)

    t0 = time.perf_counter()
    before_r = await tx(before)
    after_r = await tx(after)
    out = {"available": True, "model": asr.MODEL_NAME, "before": before_r, "after": after_r,
           "confidence_delta": (after_r["confidence"] - before_r["confidence"])}

    if reference_audio is not None:
        ref = await tx(reference_audio)
        wb = asr.wer(ref["text"], before_r["text"])
        wa = asr.wer(ref["text"], after_r["text"])
        out["reference"] = {"text": ref["text"]}
        out["wer_before"] = wb["wer"]
        out["wer_after"] = wa["wer"]
        out["wer_delta"] = (None if wb["wer"] is None or wa["wer"] is None
                            else round(wb["wer"] - wa["wer"], 3))
    out["asr_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return JSONResponse(out)


@app.websocket("/api/stream")
async def stream(ws: WebSocket):
    """Live mic path. Client streams int16 PCM frames; we feed them to a
    persistent Sanas processor and stream processed int16 back, in real time.
    Control messages (JSON text): {"type":"config","model":..,"enabled":bool}.
    When the model is toggled OFF we echo the raw input so the user A/Bs their own
    voice against the model. The real SDK is required — if it's unavailable the
    stream reports so and sends no audio (there is no mock)."""
    await ws.accept()
    loop = asyncio.get_running_loop()
    DEFAULT_FRAME = 320  # 20ms @ 16k, framing for the model-off raw bypass
    sess = None
    enabled = True
    model = client.model
    sr = MODEL_SAMPLE_RATES.get(model, 16000)
    frame = DEFAULT_FRAME
    residual = np.zeros(0, dtype=np.int16)

    async def open_session(new_model):
        nonlocal sess, model, sr, frame, residual
        if sess is not None:
            await loop.run_in_executor(None, sess.close); sess = None
        model = new_model
        sr = MODEL_SAMPLE_RATES.get(model, 16000)
        residual = np.zeros(0, dtype=np.int16)
        frame = DEFAULT_FRAME
        err = None
        if client.mode == "real" and client._initialized:
            try:
                sess = await loop.run_in_executor(None, client.create_stream, model)
                frame = sess.frame_samples
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
        await ws.send_text(json.dumps({"type": "ready", "model": model, "sample_rate": sr,
                                       "mode": client.mode, "frame": frame, "enabled": enabled,
                                       "error": err}))

    try:
        await open_session(model)
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            text, data = msg.get("text"), msg.get("bytes")
            if text:
                try: cfg = json.loads(text)
                except Exception: continue
                if cfg.get("type") == "config":
                    if "enabled" in cfg:
                        enabled = bool(cfg["enabled"])
                    nm = cfg.get("model")
                    if nm and nm != model:
                        await open_session(nm)
                    else:
                        await ws.send_text(json.dumps({"type": "state", "enabled": enabled, "model": model}))
                continue
            if data is None:
                continue
            ints = np.frombuffer(data, dtype=np.int16)
            if sess is None:                          # engine unavailable — no processing, no fake audio
                continue
            if not enabled:                           # model OFF: raw monitor for an honest A/B
                await ws.send_bytes(ints.tobytes()); continue
            buf = np.concatenate([residual, ints])
            n = len(buf) // frame
            if n == 0:
                residual = buf; continue
            chunk, residual = buf[:n * frame], buf[n * frame:]
            floats = chunk.astype(np.float32) / 32768.0

            def run():
                out = []
                for i in range(n):
                    out.extend(sess.process(floats[i * frame:(i + 1) * frame].tolist()))
                return out

            out = await loop.run_in_executor(None, run)
            arr = (np.clip(np.asarray(out, dtype=np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)
            await ws.send_bytes(arr.tobytes())
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if sess is not None:
            try: await loop.run_in_executor(None, sess.close)
            except Exception: pass


# Serve only the front-end files by name — never the backend source, .env, or vendor/.
_ALLOWED_STATIC = {"index.html", "app.js", "styles.css", "config.js", "admin.html"}
# no-cache so the browser always revalidates and picks up edits immediately
_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers=_NO_CACHE)


@app.get("/{fname}")
def static_file(fname: str) -> FileResponse:
    if fname not in _ALLOWED_STATIC:
        raise HTTPException(status_code=404, detail="Not found")
    fp = WEB_DIR / fname
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(fp, headers=_NO_CACHE)
