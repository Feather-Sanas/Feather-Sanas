"""
San backend — orchestrator surface for the Sanas Speech AI consultant.

Endpoints:
  GET  /api/health         -> SDK init status, mode (real|mock), active processors
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
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
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

import asr  # noqa: E402  (after dotenv load)
import llm  # noqa: E402
import webindex  # noqa: E402
from sanas_client import client, MODEL_SAMPLE_RATES  # noqa: E402
from twilio_routes import router as twilio_router  # noqa: E402

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # generous cap; spec limits clips to ~2 min
# In Docker the front-end lives in a dedicated dir (WEB_DIR env); for local dev
# it sits one level up from server/ (the project root).
WEB_DIR = Path(os.getenv("WEB_DIR", Path(__file__).resolve().parent.parent))

app = FastAPI(title="San — Sanas SDK orchestrator", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.include_router(twilio_router)   # /api/twilio/* (human handoff + IVR via Twilio)


@app.on_event("startup")
def _startup() -> None:
    # Connect to the SIP endpoint off the startup path so the server binds and
    # serves immediately; health reports mode='mock' until the connection is up.
    threading.Thread(target=client.initialize, daemon=True).start()


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
    return JSONResponse(h)


def _last_user(msgs: list[dict]) -> str:
    for m in reversed(msgs):
        if m["role"] == "user":
            return m["content"]
    return ""


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    messages: list[ChatTurn]
    persona: str | None = None
    skeptic: float = 0.0


@app.post("/api/chat")
def chat(req: ChatReq) -> JSONResponse:
    """Generate San's reply via Claude. Returns mode='fallback' (text=None)
    when no API key is configured, so the client uses its rule-based engine."""
    msgs = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    # API requires the history to start with a user turn and be non-empty
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages")
    sources = webindex.search(_last_user(msgs), k=3)
    text = llm.chat(msgs, req.persona, req.skeptic, context=sources)
    return JSONResponse({
        "text": text,
        "mode": "llm" if text else "fallback",
        "model": llm.MODEL if text else None,
        "sources": [{"title": s["title"], "url": s["url"]} for s in sources],
    })


@app.post("/api/chat/stream")
def chat_stream(req: ChatReq):
    """Stream San's reply token-by-token as plain-text chunks. The X-San-Mode
    response header is 'llm' when streaming real content, 'fallback' (empty body)
    when no key is configured — the client then uses its rule-based reply."""
    msgs = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages")
    sources = webindex.search(_last_user(msgs), k=3)
    src_hdr = json.dumps([{"title": s["title"], "url": s["url"]} for s in sources])  # ASCII, one line
    if not llm.available():
        return Response(content=b"", media_type="text/plain",
                        headers={"X-San-Mode": "fallback", "X-San-Sources": src_hdr,
                                 "Access-Control-Expose-Headers": "*"})

    def gen():
        for delta in llm.chat_stream(msgs, req.persona, req.skeptic, context=sources):
            yield delta

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"X-San-Mode": "llm", "X-Sanas-Model": llm.MODEL,
                                      "X-San-Sources": src_hdr,
                                      "Access-Control-Expose-Headers": "*",
                                      "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
async def process(file: UploadFile = File(...), model: str | None = None):
    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    model = model or client.model
    sr = MODEL_SAMPLE_RATES.get(model, client.sample_rate)

    t0 = time.perf_counter()
    samples = _decode_to_pcm(raw, sr)
    # The real engine runs in real time, so wall-clock ≈ clip duration. Cap the
    # clip so an upload can't hang the request for minutes (SAN_MAX_CLIP_S).
    max_clip_s = float(os.getenv("SAN_MAX_CLIP_S", "30"))
    max_samples = int(max_clip_s * sr)
    truncated = len(samples) > max_samples
    if truncated:
        samples = samples[:max_samples]
    t_ingress = time.perf_counter()
    probe = _ingress_probe(samples, sr)
    processed = client.process(samples, sr, model)
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


@app.post("/api/asr")
async def asr_compare(
    before: UploadFile = File(...),
    after: UploadFile = File(...),
    reference_audio: UploadFile | None = File(None),
):
    """Transcribe before/after audio with a real ASR (faster-whisper).
    If a clean `reference_audio` is supplied (curated scenarios send the clean
    voice bed), compute true WER for each and the WER delta; otherwise report the
    recognition-confidence delta (uploads have no clean reference)."""
    if not asr.available():
        return JSONResponse({"available": False,
                             "detail": "faster-whisper not installed on this backend"})

    sr = 16000  # Whisper operates at 16 kHz

    async def tx(f: UploadFile):
        raw = await f.read()
        if not raw:
            raise HTTPException(status_code=400, detail="empty audio")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="file too large")
        return asr.transcribe(_decode_to_pcm(raw, sr), sr)

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
    When disabled (or in mock mode) we echo the raw input so the user A/Bs their
    own voice against the model."""
    await ws.accept()
    loop = asyncio.get_running_loop()
    DEFAULT_FRAME = 320  # 20ms @ 16k, used for mock/bypass framing
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
            if not enabled or sess is None:           # bypass: raw monitor / mock
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
_ALLOWED_STATIC = {"index.html", "app.js", "styles.css"}
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
