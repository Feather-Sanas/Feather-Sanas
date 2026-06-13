"""
Twilio voice handoff — talk to a human or an IVR, with the call audio routed
through the Sanas SDK so callers hear the enhanced/cleaned stream live.

Two connection methods (both scaffolded; enabled when the matching env is set):
  • Phone callback  — POST /api/twilio/call → Twilio REST dials the user's phone
                       and runs our TwiML (human dial, IVR menu, or Sanas demo).
  • In-browser voice — GET /api/twilio/token mints a Voice access token for the
                       Twilio Voice JS SDK (Device.connect() → our TwiML app).

The centerpiece is the **Media Streams** WebSocket /api/twilio/media: Twilio sends
the call's 8 kHz μ-law audio, we run it through the Sanas telephony model
(AGENTIC_VI_GT_NC) and stream the processed audio back into the call — showing how
Sanas improves a phone call / IVR in real time.

No Twilio SDK dependency: REST via urllib, the Voice JWT is hand-signed (HS256),
μ-law via stdlib `audioop`. Everything degrades gracefully when unconfigured.

Setup (server/.env):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER          # REST callback
  TWILIO_HUMAN_NUMBER                                           # who "talk to a human" dials
  TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_TWIML_APP_SID  # browser Voice SDK
  PUBLIC_BASE_URL=https://<your-tunnel>                         # public https for TwiML + wss
  TWILIO_SANAS_MODEL=AGENTIC_VI_GT_NC                           # 8k telephony model
Point your Twilio number's Voice webhook (and the TwiML App's Voice URL) at
  {PUBLIC_BASE_URL}/api/twilio/voice
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape

import numpy as np
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

try:
    import audioop  # stdlib (μ-law <-> PCM); present through Python 3.12
    _AUDIOOP = True
except Exception:
    audioop = None  # type: ignore
    _AUDIOOP = False

import sanas_client

router = APIRouter()

SID = os.getenv("TWILIO_ACCOUNT_SID")
TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
NUMBER = os.getenv("TWILIO_NUMBER")
HUMAN = os.getenv("TWILIO_HUMAN_NUMBER")
API_KEY = os.getenv("TWILIO_API_KEY_SID")
API_SECRET = os.getenv("TWILIO_API_KEY_SECRET")
APP_SID = os.getenv("TWILIO_TWIML_APP_SID")
PUBLIC_BASE = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
SANAS_MODEL = os.getenv("TWILIO_SANAS_MODEL", "AGENTIC_VI_GT_NC")
TW_SR = 8000  # Twilio Media Streams are 8 kHz μ-law


# ---- capability detection (mirrors the graceful pattern used elsewhere) ----
def _cfg() -> dict:
    callback = all([SID, TOKEN, NUMBER, PUBLIC_BASE])
    browser = all([SID, API_KEY, API_SECRET, APP_SID])
    return {
        "phone_callback": callback,           # POST /api/twilio/call works
        "browser_voice": browser,             # /api/twilio/token works
        "ivr": bool(PUBLIC_BASE),             # TwiML reachable
        "human_dial": bool(HUMAN),            # a destination to dial
        "sanas_in_call": bool(PUBLIC_BASE) and _AUDIOOP,
        "public_base": PUBLIC_BASE or None,
        "model": SANAS_MODEL,
        "audioop": _AUDIOOP,
    }


@router.get("/api/twilio/config")
def twilio_config() -> JSONResponse:
    return JSONResponse(_cfg())


# ---- TwiML builders ---------------------------------------------------------
def _ws_url(model: str | None = None) -> str:
    m = model or SANAS_MODEL
    return PUBLIC_BASE.replace("https://", "wss://").replace("http://", "ws://") + \
        f"/api/twilio/media?model={urllib.parse.quote(m)}"


def _twiml_sanas_demo(model: str | None = None) -> str:
    # <Connect><Stream> hands the call's bidirectional media to our WebSocket,
    # where Sanas processes it and streams the cleaned audio back.
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        '<Say>Connecting you through Sanas. You will hear your own audio, '
        'enhanced in real time.</Say>'
        f'<Connect><Stream url="{escape(_ws_url(model))}"/></Connect>'
        '</Response>'
    )


def _twiml_dial(to: str, model: str | None = None) -> str:
    # Two-way: bridge the browser caller to a real phone (<Dial>), and fork the
    # call audio to our Sanas WS (<Start><Stream>) so the selected model runs and
    # the mid-call on/off applies. (Media Streams can't re-inject into a Dial leg —
    # that needs <Connect><Stream>, which can't co-exist with <Dial>.)
    if not to:
        return _twiml_ivr()
    fork = f'<Start><Stream url="{escape(_ws_url(model))}"/></Start>' if (PUBLIC_BASE and _AUDIOOP) else ''
    caller = f' callerId="{escape(NUMBER)}"' if NUMBER else ''
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'{fork}<Dial{caller}><Number>{escape(to)}</Number></Dial></Response>')


# ---- true in-path bridge: two <Connect><Stream> legs joined on our server -----
def _bridge_ws(bid: str, role: str, model: str | None, to: str | None = None) -> str:
    base = PUBLIC_BASE.replace("https://", "wss://").replace("http://", "ws://")
    q = f"id={urllib.parse.quote(bid)}&role={role}&model={urllib.parse.quote(model or SANAS_MODEL)}"
    if to:
        q += f"&to={urllib.parse.quote(to)}"
    return f"{base}/api/twilio/bridge?{q}"


def _twiml_bridge_caller(bid: str, to: str, model: str | None) -> str:
    # the browser leg: bidirectional stream to our bridge (which dials the callee)
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Connect><Stream url="{escape(_bridge_ws(bid, "caller", model, to))}"/></Connect></Response>')


def _twiml_bridge_callee(bid: str, model: str | None) -> str:
    # the dialed-person leg: bidirectional stream to the same bridge
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Connect><Stream url="{escape(_bridge_ws(bid, "callee", model))}"/></Connect></Response>')


def _create_call(to: str, url: str) -> dict:
    """Place an outbound call whose media is controlled by `url` (TwiML).
    On a Twilio API error, raises RuntimeError carrying the status + body so the
    caller can be told *why* (e.g. error 21219 = destination not verified)."""
    payload = urllib.parse.urlencode({"To": to, "From": NUMBER, "Url": url}).encode()
    api = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls.json"
    auth = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    req = urllib.request.Request(api, data=payload, method="POST",
                                 headers={"Authorization": f"Basic {auth}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        raise RuntimeError(f"twilio {e.code}: {body}") from None


def _update_call_twiml(call_sid: str, twiml: str) -> dict:
    """Redirect a live call to fresh inline TwiML (used to speak a dial failure)."""
    payload = urllib.parse.urlencode({"Twiml": twiml}).encode()
    api = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls/{call_sid}.json"
    auth = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    req = urllib.request.Request(api, data=payload, method="POST",
                                 headers={"Authorization": f"Basic {auth}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _twiml_say_hangup(message: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<Response><Say>{escape(message)}</Say><Hangup/></Response>')


def _sanas_mulaw(sess, payload_b64: str) -> str:
    """μ-law (8k) → Sanas model → μ-law, for one Media Streams frame."""
    ints = np.frombuffer(audioop.ulaw2lin(base64.b64decode(payload_b64), 2), dtype=np.int16)
    floats = ints.astype(np.float32) / 32768.0
    fr = sess.frame_samples
    out: list[float] = []
    for i in range(0, max(0, len(floats) - fr + 1), fr):
        out.extend(sess.process(floats[i:i + fr].tolist()))
    if not out:
        return payload_b64
    arr = (np.clip(np.asarray(out, dtype=np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)
    return base64.b64encode(audioop.lin2ulaw(arr.tobytes(), 2)).decode()


def _twiml_human() -> str:
    if not HUMAN:
        return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
                '<Say>No human destination is configured yet. Goodbye.</Say></Response>')
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            '<Say>Connecting you to a specialist.</Say>'
            f'<Dial>{escape(HUMAN)}</Dial></Response>')


def _twiml_ivr() -> str:
    action = f"{PUBLIC_BASE}/api/twilio/gather"
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f'<Gather numDigits="1" action="{escape(action)}" method="POST" timeout="8">'
        '<Say>Welcome to Sanas. Press 1 to speak to a specialist. '
        'Press 2 to hear your call enhanced by Sanas in real time.</Say>'
        '</Gather>'
        '<Say>We did not get a selection. Goodbye.</Say>'
        '</Response>'
    )


# DTMF model menu used during a dial-in call (digit -> model; "0" = Sanas off)
DTMF_MODELS = {"1": "AGENTIC_VI_GT_NC", "2": "SE2.2", "3": "VI_G_NC3.0"}
DTMF_MENU = ("Press 1 for noise cancellation, 2 for speech enhancement, "
             "3 for voice isolation, or 0 to turn Sanas off.")


def _twiml_dialin() -> str:
    # Inbound: ask the caller to key in the number they want to reach.
    action = f"{PUBLIC_BASE}/api/twilio/dialin-connect"
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Gather input="dtmf" finishOnKey="#" timeout="12" action="{escape(action)}" method="POST">'
            '<Say>Welcome to Sanas. Enter the number you would like to call, '
            'with country code, then press pound.</Say>'
            '</Gather>'
            '<Say>No number entered. Goodbye.</Say></Response>')


def _twiml_dialin_connect(call_sid: str, to: str, model: str | None = None) -> str:
    if not to:
        return _twiml_dialin()
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Say>Connecting you now. {DTMF_MENU}</Say>'
            f'<Connect><Stream url="{escape(_bridge_ws(call_sid, "caller", model or SANAS_MODEL, to))}"/></Connect>'
            '</Response>')


@router.api_route("/api/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request) -> Response:
    # mode may arrive as a query param (REST callback Url) or a POST form field
    # (browser Device.connect params are POSTed to the TwiML App's Voice URL).
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            for k, v in form.items():
                params.setdefault(k, v)
        except Exception:
            pass
    mode = params.get("mode") or ("dial" if params.get("To") else "dialin")
    model = params.get("model")
    if mode == "bridge":          # browser leg of the in-path bridge
        body = _twiml_bridge_caller((params.get("bridge") or "").strip(),
                                    (params.get("To") or "").strip(), model)
    elif mode == "bridgeleg":     # dialed-person leg of the bridge
        body = _twiml_bridge_callee((params.get("id") or "").strip(), model)
    elif mode == "dial":
        body = _twiml_dial((params.get("To") or "").strip(), model)
    elif mode == "human":
        body = _twiml_human()
    elif mode == "sanas":
        body = _twiml_sanas_demo(model)
    elif mode == "ivr":
        body = _twiml_ivr()
    else:
        body = _twiml_dialin()        # default for an inbound call to the number
    return Response(content=body, media_type="application/xml")


@router.post("/api/twilio/dialin-connect")
async def twilio_dialin_connect(request: Request) -> Response:
    form = await request.form()
    digits = "".join(ch for ch in (form.get("Digits") or "") if ch.isdigit())
    call_sid = (form.get("CallSid") or "").strip() or f"dialin-{int(time.time())}"
    if not digits:
        return Response(_twiml_dialin(), media_type="application/xml")
    to = ("+1" + digits) if len(digits) == 10 else ("+" + digits)   # 10 digits → assume US
    return Response(_twiml_dialin_connect(call_sid, to, SANAS_MODEL), media_type="application/xml")


@router.post("/api/twilio/gather")
async def twilio_gather(request: Request) -> Response:
    form = await request.form()
    digit = (form.get("Digits") or "").strip()
    body = _twiml_human() if digit == "1" else _twiml_sanas_demo() if digit == "2" else _twiml_ivr()
    return Response(content=body, media_type="application/xml")


# ---- click-to-call (Twilio REST, urllib + basic auth) -----------------------
@router.post("/api/twilio/call")
async def twilio_call(request: Request) -> JSONResponse:
    if not _cfg()["phone_callback"]:
        return JSONResponse({"ok": False, "detail": "Twilio callback not configured "
                             "(need TWILIO_ACCOUNT_SID/AUTH_TOKEN/NUMBER + PUBLIC_BASE_URL)."}, status_code=200)
    data = await request.json()
    to = (data.get("to") or "").strip()
    mode = data.get("mode", "ivr")
    if not to:
        return JSONResponse({"ok": False, "detail": "Provide a phone number to call."}, status_code=400)
    voice_url = f"{PUBLIC_BASE}/api/twilio/voice?mode={urllib.parse.quote(mode)}"
    payload = urllib.parse.urlencode({"To": to, "From": NUMBER, "Url": voice_url}).encode()
    api = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls.json"
    auth = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    req = urllib.request.Request(api, data=payload, method="POST",
                                 headers={"Authorization": f"Basic {auth}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read().decode())
        return JSONResponse({"ok": True, "sid": out.get("sid"), "status": out.get("status"), "mode": mode})
    except urllib.error.HTTPError as e:
        return JSONResponse({"ok": False, "detail": f"Twilio {e.code}: {e.read().decode()[:200]}"}, status_code=200)
    except Exception as e:
        return JSONResponse({"ok": False, "detail": f"{type(e).__name__}: {e}"}, status_code=200)


# ---- Voice access token for the browser SDK (hand-signed JWT) ---------------
def _voice_token(identity: str) -> str:
    now = int(time.time())
    header = {"typ": "JWT", "alg": "HS256", "cty": "twilio-fpa;v=1"}
    grants = {"identity": identity,
              "voice": {"outgoing": {"application_sid": APP_SID}, "incoming": {"allow": True}}}
    payload = {"jti": f"{API_KEY}-{now}", "iss": API_KEY, "sub": SID,
               "iat": now, "nbf": now, "exp": now + 3600, "grants": grants}
    seg = lambda o: base64.urlsafe_b64encode(json.dumps(o, separators=(",", ":")).encode()).rstrip(b"=")
    signing = seg(header) + b"." + seg(payload)
    sig = base64.urlsafe_b64encode(hmac.new(API_SECRET.encode(), signing, hashlib.sha256).digest()).rstrip(b"=")
    return (signing + b"." + sig).decode()


# ---- mid-call model on/off ---------------------------------------------------
# STREAMS: single-leg media (keyed by CallSid). BRIDGES: two-leg in-path bridge
# (keyed by a browser-generated bridge id). Both expose an `enabled` flag the
# media loop reads each frame so the caller can A/B Sanas vs the raw line live.
STREAMS: dict[str, dict] = {}
BRIDGES: dict[str, dict] = {}


@router.post("/api/twilio/toggle")
async def twilio_toggle(request: Request) -> JSONResponse:
    d = await request.json()
    enabled = bool(d.get("enabled", True))
    bridge_id = (d.get("bridge_id") or "").strip()
    if bridge_id:
        BRIDGES.setdefault(bridge_id, {})["enabled"] = enabled
        return JSONResponse({"ok": True, "bridge_id": bridge_id, "enabled": enabled})
    call_sid = (d.get("call_sid") or "").strip()
    if not call_sid:
        return JSONResponse({"ok": False, "detail": "call_sid or bridge_id required"}, status_code=400)
    STREAMS.setdefault(call_sid, {"enabled": True})["enabled"] = enabled
    return JSONResponse({"ok": True, "call_sid": call_sid, "enabled": enabled})


@router.get("/api/twilio/token")
def twilio_token() -> JSONResponse:
    if not _cfg()["browser_voice"]:
        return JSONResponse({"ok": False, "detail": "Browser voice not configured "
                             "(need TWILIO_ACCOUNT_SID + API key/secret + TWIML_APP_SID)."}, status_code=200)
    identity = f"sani-{int(time.time())}"
    return JSONResponse({"ok": True, "token": _voice_token(identity), "identity": identity})


# ---- Media Streams WS: call audio → Sanas → back into the call --------------
@router.websocket("/api/twilio/media")
async def twilio_media(ws: WebSocket):
    import asyncio
    await ws.accept()
    loop = asyncio.get_running_loop()
    model = ws.query_params.get("model", SANAS_MODEL)
    sess = None
    stream_sid = None
    call_sid = None
    residual = np.zeros(0, dtype=np.int16)
    frame = int(TW_SR * 0.02)  # 160 samples / 20ms

    def echo(payload_b64):
        return ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid,
                                        "media": {"payload": payload_b64}}))

    try:
        while True:
            raw = await ws.receive_text()           # Twilio sends JSON text frames
            msg = json.loads(raw)
            ev = msg.get("event")
            if ev == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid") or stream_sid
                STREAMS.setdefault(call_sid, {"enabled": True})
                if sanas_client.client.mode == "real" and _AUDIOOP:
                    try:
                        sess = await loop.run_in_executor(None, sanas_client.client.create_stream, model, TW_SR)
                        frame = sess.frame_samples
                    except Exception:
                        sess = None
            elif ev == "media":
                # mid-call toggle: when the model is off (or unavailable), echo the
                # raw line so the caller A/Bs against Sanas live.
                enabled = STREAMS.get(call_sid, {}).get("enabled", True)
                if sess is None or not _AUDIOOP or not enabled:
                    await echo(msg["media"]["payload"])
                    continue
                pcm = audioop.ulaw2lin(base64.b64decode(msg["media"]["payload"]), 2)
                ints = np.frombuffer(pcm, dtype=np.int16)
                buf = np.concatenate([residual, ints])
                n = len(buf) // frame
                if n == 0:
                    residual = buf
                    continue
                chunk, residual = buf[:n * frame], buf[n * frame:]
                floats = chunk.astype(np.float32) / 32768.0

                def run():
                    out = []
                    for i in range(n):
                        out.extend(sess.process(floats[i * frame:(i + 1) * frame].tolist()))
                    return out

                out = await loop.run_in_executor(None, run)
                arr = (np.clip(np.asarray(out, dtype=np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)
                ulaw = audioop.lin2ulaw(arr.tobytes(), 2)
                await ws.send_text(json.dumps({
                    "event": "media", "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(ulaw).decode()},
                }))
            elif ev == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if call_sid:
            STREAMS.pop(call_sid, None)
        if sess is not None:
            try: await loop.run_in_executor(None, sess.close)
            except Exception: pass


def _open_sess(model: str):
    return sanas_client.client.create_stream(model, sanas_client.MODEL_SAMPLE_RATES.get(model, TW_SR))


def _process_caller(br: dict, payload_b64: str):
    """μ-law(8k) caller frame → current Sanas model (resampled if the model runs at
    16k) → μ-law(8k). Returns None while buffering a partial frame, or the raw
    payload when Sanas is off / no session."""
    sess = br.get("sess")
    if sess is None or not br.get("enabled", True):
        return payload_b64
    sr = sess.sample_rate
    pcm = audioop.ulaw2lin(base64.b64decode(payload_b64), 2)
    if sr != TW_SR:
        pcm, br["up"] = audioop.ratecv(pcm, 2, 1, TW_SR, sr, br.get("up"))
    ints = np.frombuffer(pcm, dtype=np.int16)
    resid = br.get("resid")
    buf = np.concatenate([resid, ints]) if (resid is not None and len(resid)) else ints
    fr = sess.frame_samples
    n = len(buf) // fr
    if n == 0:
        br["resid"] = buf
        return None
    chunk, br["resid"] = buf[:n * fr], buf[n * fr:]
    floats = chunk.astype(np.float32) / 32768.0
    out = []
    for i in range(n):
        out.extend(sess.process(floats[i * fr:(i + 1) * fr].tolist()))
    arr = (np.clip(np.asarray(out, dtype=np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)
    pcm_out = arr.tobytes()
    if sr != TW_SR:
        pcm_out, br["down"] = audioop.ratecv(pcm_out, 2, 1, sr, TW_SR, br.get("down"))
    return base64.b64encode(audioop.lin2ulaw(pcm_out, 2)).decode()


_TONE_HZ = {"AGENTIC_VI_GT_NC": 880, "SE2.2": 1320, "VI_G_NC3.0": 1760}  # per-model confirm pitch


async def _confirm_tone(br: dict, freq: int, ms: int = 180):
    """Play a short windowed tone into the caller's ear to confirm a DTMF action.
    (A <Connect><Stream> owns the media, so we inject audio rather than <Say>.)"""
    caller, sid = br.get("caller"), br.get("caller_sid")
    if not caller or not sid or not _AUDIOOP:
        return
    n = int(TW_SR * ms / 1000)
    win = np.hanning(n) if n > 1 else np.ones(n)
    pcm = (np.sin(2 * np.pi * freq * np.arange(n) / TW_SR) * 7000 * win).astype(np.int16)
    payload = base64.b64encode(audioop.lin2ulaw(pcm.tobytes(), 2)).decode()
    try:
        await caller.send_text(json.dumps({"event": "media", "streamSid": sid,
                                           "media": {"payload": payload}}))
    except Exception:
        pass


async def _bridge_dtmf(br: dict, digit: str, loop):
    """In-call DTMF: 0 = Sanas off; 1/2/3 = switch model (recreates the processor).
    Each action plays a short confirmation tone back to the caller."""
    if digit == "0":
        br["enabled"] = False
        await _confirm_tone(br, 440)            # low tone = off
        return
    model = DTMF_MODELS.get(digit)
    if not model:
        return
    br["enabled"] = True
    freq = _TONE_HZ.get(model, 1000)
    if model == br.get("model") and br.get("sess") is not None:
        await _confirm_tone(br, freq)
        return
    old = br.get("sess")
    br["sess"] = None
    if old is not None:
        try: await loop.run_in_executor(None, old.close)
        except Exception: pass
    br["up"] = br["down"] = None
    br["resid"] = None
    if sanas_client.client.mode == "real" and _AUDIOOP:
        try:
            br["sess"] = await loop.run_in_executor(None, _open_sess, model)
            br["model"] = model
        except Exception:
            br["sess"] = None
    await _confirm_tone(br, freq)               # confirm after the (re)create


@router.websocket("/api/twilio/bridge")
async def twilio_bridge(ws: WebSocket):
    """True in-path bridge: the browser ('caller') and the dialed phone ('callee')
    each open a bidirectional <Connect><Stream> to this endpoint, keyed by a shared
    bridge id. The caller's audio is run through the selected Sanas model before it
    is forwarded to the callee — so the person actually hears the cleaned voice. The
    callee's audio is relayed back to the browser unprocessed. /api/twilio/toggle
    (bridge_id) flips Sanas on/off live."""
    import asyncio
    await ws.accept()
    loop = asyncio.get_running_loop()
    qp = ws.query_params
    bid = qp.get("id") or ""
    role = qp.get("role") or "caller"
    model = qp.get("model") or SANAS_MODEL
    to = qp.get("to")
    br = BRIDGES.setdefault(bid, {"enabled": True})
    stream_sid = None
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            ev = msg.get("event")
            if ev == "start":
                stream_sid = msg["start"]["streamSid"]
                br[role] = ws
                br[f"{role}_sid"] = stream_sid
                if role == "caller":
                    br.setdefault("enabled", True)
                    br["model"] = model
                    br["up"] = br["down"] = None
                    br["resid"] = None
                    br["caller_call_sid"] = msg["start"].get("callSid")
                    if sanas_client.client.mode == "real" and _AUDIOOP:
                        try:
                            br["sess"] = await loop.run_in_executor(None, _open_sess, model)
                        except Exception:
                            br["sess"] = None
                    # dial the person; their leg streams back as role=callee
                    if to and _cfg()["phone_callback"]:
                        url = f"{PUBLIC_BASE}/api/twilio/voice?mode=bridgeleg&id={urllib.parse.quote(bid)}&model={urllib.parse.quote(model)}"
                        try:
                            await loop.run_in_executor(None, _create_call, to, url)
                        except Exception as e:
                            # Couldn't reach the callee — tell the caller why instead of
                            # leaving dead air. 21219 = destination not a Verified Caller ID
                            # (trial accounts only); other codes = bad/unreachable number.
                            detail = str(e)
                            unverified = "21219" in detail or "not verified" in detail.lower()
                            say = ("The number you dialed has not been verified on this Twilio "
                                   "account yet. Verify it in the Twilio console, or upgrade the "
                                   "account, then try again. Goodbye." if unverified else
                                   "Sorry, that call could not be connected. Please check the "
                                   "number and try again. Goodbye.")
                            csid = br.get("caller_call_sid")
                            if csid:
                                try:
                                    await loop.run_in_executor(None, _update_call_twiml, csid, _twiml_say_hangup(say))
                                except Exception:
                                    pass
            elif ev == "dtmf" and role == "caller":
                digit = (msg.get("dtmf") or {}).get("digit")
                if digit:
                    await _bridge_dtmf(br, digit, loop)
            elif ev == "media":
                payload = msg["media"]["payload"]
                if role == "caller":
                    try:
                        out_payload = await loop.run_in_executor(None, _process_caller, br, payload)
                    except Exception:
                        out_payload = payload         # never drop the call on a transient (e.g. mid-switch)
                    if out_payload is None:
                        continue                      # buffering a partial (resampled) frame
                    tgt, tsid = br.get("callee"), br.get("callee_sid")
                else:  # callee → caller, relayed as-is
                    out_payload, tgt, tsid = payload, br.get("caller"), br.get("caller_sid")
                if tgt is not None and tsid:
                    try:
                        await tgt.send_text(json.dumps({"event": "media", "streamSid": tsid,
                                                        "media": {"payload": out_payload}}))
                    except Exception:
                        pass
            elif ev == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        b = BRIDGES.get(bid)
        if b:
            b.pop(role, None); b.pop(f"{role}_sid", None)
            if role == "caller" and b.get("sess") is not None:
                try: await loop.run_in_executor(None, b["sess"].close)
                except Exception: pass
                b["sess"] = None
            if not b.get("caller") and not b.get("callee"):
                BRIDGES.pop(bid, None)
