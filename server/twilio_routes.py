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
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

try:
    import audioop  # stdlib (μ-law <-> PCM); present through Python 3.12
    _AUDIOOP = True
except Exception:
    audioop = None  # type: ignore
    _AUDIOOP = False

import auth
import sanas_client

router = APIRouter()

SID = os.getenv("TWILIO_ACCOUNT_SID")
TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
NUMBER = os.getenv("TWILIO_NUMBER")
HUMAN = os.getenv("TWILIO_HUMAN_NUMBER")
API_KEY = os.getenv("TWILIO_API_KEY_SID")
API_SECRET = os.getenv("TWILIO_API_KEY_SECRET")
APP_SID = os.getenv("TWILIO_TWIML_APP_SID")
# Push credentials — let INCOMING and app-to-app (client) calls ring a mobile
# device. iOS needs an APNs-VoIP credential and Android an FCM one, so they're
# separate SIDs; the token endpoint picks by ?platform=. TWILIO_PUSH_CREDENTIAL_SID
# is a generic fallback. Optional: outgoing PSTN + the in-app Sanas loopback work
# without any of these.
PUSH_CREDENTIAL_SID = os.getenv("TWILIO_PUSH_CREDENTIAL_SID")
PUSH_CREDENTIAL_SID_IOS = os.getenv("TWILIO_PUSH_CREDENTIAL_SID_IOS")
PUSH_CREDENTIAL_SID_ANDROID = os.getenv("TWILIO_PUSH_CREDENTIAL_SID_ANDROID")
PUBLIC_BASE = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")


def _push_cred_for(platform: str | None) -> str | None:
    """The right push credential SID for a client platform (iOS→APNs, Android→FCM),
    falling back to the generic one."""
    p = (platform or "").lower()
    if p == "ios":
        return PUSH_CREDENTIAL_SID_IOS or PUSH_CREDENTIAL_SID
    if p == "android":
        return PUSH_CREDENTIAL_SID_ANDROID or PUSH_CREDENTIAL_SID
    return PUSH_CREDENTIAL_SID
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
        # incoming / app-to-app can ring a device (any platform credential configured)
        "push_credential": bool(PUSH_CREDENTIAL_SID or PUSH_CREDENTIAL_SID_IOS or PUSH_CREDENTIAL_SID_ANDROID),
        # mobile sign-in: when required, /api/twilio/token needs a session bearer
        "auth_required": auth.required(),
        "auth_domain": auth.domain(),
        "public_base": PUBLIC_BASE or None,
        "model": SANAS_MODEL,
        "audioop": _AUDIOOP,
    }


@router.get("/api/twilio/config")
def twilio_config() -> JSONResponse:
    return JSONResponse(_cfg())


# ---- TwiML builders ---------------------------------------------------------
def _stream_xml(path: str, params: dict) -> str:
    """Build a <Stream> that passes params as <Parameter> children. Twilio does NOT
    forward a wss URL query string to the socket — customParameters (delivered in the
    'start' event) are the reliable channel. We keep the query string too as a benign
    fallback; the WS handlers read customParameters first, query second."""
    items = [(k, str(v)) for k, v in params.items() if v not in (None, "")]
    base = PUBLIC_BASE.replace("https://", "wss://").replace("http://", "ws://")
    qs = ("?" + urllib.parse.urlencode(items)) if items else ""
    url = escape(base + path + qs)
    children = "".join(f'<Parameter name="{escape(k)}" value="{escape(v)}"/>' for k, v in items)
    return f'<Stream url="{url}">{children}</Stream>'


def _twiml_sanas_demo(model: str | None = None) -> str:
    # <Connect><Stream> hands the call's bidirectional media to our WebSocket,
    # where Sanas processes it and streams the cleaned audio back.
    stream = _stream_xml("/api/twilio/media", {"model": model or SANAS_MODEL})
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        '<Say>Connecting you through Sanas. You will hear your own audio, '
        'enhanced in real time.</Say>'
        f'<Connect>{stream}</Connect>'
        '</Response>'
    )


def _twiml_dial(to: str, model: str | None = None) -> str:
    # Two-way: bridge the browser caller to a real phone (<Dial>), and fork the
    # call audio to our Sanas WS (<Start><Stream>) so the selected model runs and
    # the mid-call on/off applies. (Media Streams can't re-inject into a Dial leg —
    # that needs <Connect><Stream>, which can't co-exist with <Dial>.)
    if not to:
        return _twiml_ivr()
    fork = (f'<Start>{_stream_xml("/api/twilio/media", {"model": model or SANAS_MODEL})}</Start>'
            if (PUBLIC_BASE and _AUDIOOP) else '')
    caller = f' callerId="{escape(NUMBER)}"' if NUMBER else ''
    # record both legs so the call can be fetched + analyzed afterward
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'{fork}<Dial{caller} record="record-from-answer-dual"><Number>{escape(to)}</Number></Dial></Response>')


def _twiml_client(identity: str, model: str | None = None) -> str:
    # App-to-app (WebRTC): dial another REGISTERED Voice SDK client by identity, and
    # fork the audio to our Sanas WS (<Start><Stream>) so the selected model runs and
    # the mid-call on/off applies — same shape as _twiml_dial, client target instead
    # of a phone number. The callee only rings if a push credential is configured
    # (TWILIO_PUSH_CREDENTIAL_SID) and it registered its device token.
    if not identity:
        return _twiml_sanas_demo(model)   # nobody to dial → fall back to the loopback demo
    fork = (f'<Start>{_stream_xml("/api/twilio/media", {"model": model or SANAS_MODEL})}</Start>'
            if (PUBLIC_BASE and _AUDIOOP) else '')
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'{fork}<Dial record="record-from-answer-dual"><Client>{escape(identity)}</Client></Dial></Response>')


# ---- true in-path bridge: two <Connect><Stream> legs joined on our server -----
def _twiml_bridge_caller(bid: str, to: str, model: str | None) -> str:
    # the browser leg: bidirectional stream to our bridge (which dials the callee)
    stream = _stream_xml("/api/twilio/bridge",
                         {"id": bid, "role": "caller", "model": model or SANAS_MODEL, "to": to})
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Connect>{stream}</Connect></Response>')


def _twiml_bridge_callee(bid: str, model: str | None) -> str:
    # the dialed-person leg: bidirectional stream to the same bridge
    stream = _stream_xml("/api/twilio/bridge",
                         {"id": bid, "role": "callee", "model": model or SANAS_MODEL})
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Connect>{stream}</Connect></Response>')


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


def _twiml_human(model: str | None = None) -> str:
    if not HUMAN:
        return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
                '<Say>No human destination is configured yet. Goodbye.</Say></Response>')
    # fork the call audio through the selected Sanas model (same one-way limitation as
    # <Dial> mode — runs/measures the model and honors the mid-call on/off toggle)
    fork = (f'<Start>{_stream_xml("/api/twilio/media", {"model": model or SANAS_MODEL})}</Start>'
            if (PUBLIC_BASE and _AUDIOOP) else '')
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            '<Say>Connecting you to a specialist.</Say>'
            f'{fork}<Dial>{escape(HUMAN)}</Dial></Response>')


def _twiml_ivr(model: str | None = None) -> str:
    action = f"{PUBLIC_BASE}/api/twilio/gather"
    if model:
        action += f"?model={urllib.parse.quote(model)}"
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
    stream = _stream_xml("/api/twilio/bridge",
                         {"id": call_sid, "role": "caller", "model": model or SANAS_MODEL, "to": to})
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Say>Connecting you now. {DTMF_MENU}</Say>'
            f'<Connect>{stream}</Connect>'
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
    elif mode == "client":        # app-to-app (WebRTC): dial another SDK client by identity (passed as To)
        body = _twiml_client((params.get("To") or "").strip(), model)
    elif mode == "human":
        body = _twiml_human(model)
    elif mode == "sanas":
        body = _twiml_sanas_demo(model)
    elif mode == "demo":          # guided voice agent: capture a dialog, replay it through every model
        body = _twiml_demo_capture()
    elif mode == "ivr":
        body = _twiml_ivr(model)
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
    model = request.query_params.get("model") or (form.get("model") or "") or None
    body = (_twiml_human(model) if digit == "1"
            else _twiml_sanas_demo(model) if digit == "2"
            else _twiml_ivr(model))
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
    model = (data.get("model") or "").strip()
    if not to:
        return JSONResponse({"ok": False, "detail": "Provide a phone number to call."}, status_code=400)
    voice_url = f"{PUBLIC_BASE}/api/twilio/voice?mode={urllib.parse.quote(mode)}"
    if model:
        voice_url += f"&model={urllib.parse.quote(model)}"
    # record the whole call so the app can fetch it afterward and analyze it like an upload
    payload = urllib.parse.urlencode({"To": to, "From": NUMBER, "Url": voice_url,
                                      "Record": "true", "RecordingChannels": "mono",
                                      "Trim": "trim-silence"}).encode()
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


@router.get("/api/twilio/recording")
async def twilio_recording(call_sid: str = "") -> Response:
    """Proxy the Twilio recording of a finished call (Basic-auth stays server-side).
    Returns the WAV when ready, else {"ready": false}. The front-end polls this after
    a call and then runs the recording through /api/process — like an uploaded clip."""
    import asyncio
    if not (call_sid and SID and TOKEN):
        return JSONResponse({"ready": False, "detail": "missing call_sid or credentials"})
    auth = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()

    def _fetch():
        list_url = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls/{call_sid}/Recordings.json"
        req = urllib.request.Request(list_url, headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            recs = json.loads(r.read().decode()).get("recordings", [])
        done = [x for x in recs if x.get("status") == "completed"]
        if not done:
            return None, None
        rec = done[0]
        media = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Recordings/{rec['sid']}.wav"
        mreq = urllib.request.Request(media, headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(mreq, timeout=30) as r:
            return r.read(), rec

    try:
        wav, rec = await asyncio.get_running_loop().run_in_executor(None, _fetch)
    except Exception as e:
        return JSONResponse({"ready": False, "detail": str(e)[:200]})
    if not wav:
        return JSONResponse({"ready": False})
    return Response(content=wav, media_type="audio/wav",
                    headers={"X-Recording-Sid": rec.get("sid", ""),
                             "X-Recording-Duration": str(rec.get("duration", "")),
                             "Access-Control-Expose-Headers": "*"})


# ---- Guided voice-agent demo: capture a dialog, then replay it through every model -
# Phase 1 captures the caller's voice (ends on a spoken "done" via faster-whisper,
# silence, keypad, or a cap). Phase 2 replays that one clip through each model in real
# time so they compare identical audio. Ends asking if they'd like a Sanas callback.
DEMO_SEQUENCE = [
    ("AGENTIC_VI_GT_NC", "Noise Cancellation for telephony"),
    ("SE2.2",            "Speech Enhancement"),
    ("VI_G_NC3.0",       "Noise Cancellation with voice isolation"),
]
DEMO: dict[str, dict] = {}    # call_sid -> {"goto": "next"|"agent"}
LEADS: list[dict] = []        # callback requests captured at the end of the demo


# Playback order: the caller's own dialog, then that same clip through each model.
PLAY_ORDER = [("raw", "your original recording")] + DEMO_SEQUENCE


def _twiml_demo_capture() -> str:
    """Phase 1 — the agent asks the caller to talk, and we capture that dialog once."""
    stream = _stream_xml("/api/twilio/demo-capture", {})
    play0 = escape(f"{PUBLIC_BASE}/api/twilio/demo-play?i=0")
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            '<Say>Welcome to the Sanas live demo. First, I want to capture your voice in your real '
            'environment so I can play it back through each model. After the tone, tell me about your '
            'setup — where you take calls and what the background sounds like — then say a sentence or '
            'two you would say to a customer. Say "done", or press pound, when you finish.</Say>'
            f'<Connect>{stream}</Connect>'
            f'<Redirect>{play0}</Redirect></Response>')


def _twiml_demo_play(i: int) -> str:
    """Phase 2 — replay the captured dialog through item i of PLAY_ORDER, in real time."""
    if i >= len(PLAY_ORDER):
        return _twiml_demo_outro()
    model, label = PLAY_ORDER[i]
    stream = _stream_xml("/api/twilio/demo-play-ws", {"model": model, "i": str(i)})
    nxt = escape(f"{PUBLIC_BASE}/api/twilio/demo-play?i={i + 1}")
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Say>{i + 1} of {len(PLAY_ORDER)}: {escape(label)}. Press 1 to skip ahead.</Say>'
            f'<Connect>{stream}</Connect>'
            f'<Redirect>{nxt}</Redirect></Response>')


def _twiml_demo_outro() -> str:
    action = escape(f"{PUBLIC_BASE}/api/twilio/demo-callback")
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Gather input="speech dtmf" numDigits="1" speechTimeout="auto" action="{action}" method="POST">'
            '<Say>That is the full lineup. Would you like someone from Sanas to call you to talk about your '
            'workload and pricing, and tailor a plan to your needs? Say yes or no — or press 1 for yes.</Say>'
            f'</Gather><Redirect>{action}</Redirect></Response>')


@router.api_route("/api/twilio/demo-play", methods=["GET", "POST"])
async def twilio_demo_play(request: Request) -> Response:
    qp = dict(request.query_params)
    form = {}
    if request.method == "POST":
        try: form = dict(await request.form())
        except Exception: pass
    sid = form.get("CallSid") or qp.get("CallSid") or ""
    if sid and DEMO.get(sid, {}).get("goto") == "agent":   # caller asked for a person
        DEMO.pop(sid, None)
        return Response(_twiml_human(SANAS_MODEL), media_type="application/xml")
    i = int(qp.get("i") or form.get("i") or 0)
    return Response(_twiml_demo_play(i), media_type="application/xml")


@router.post("/api/twilio/demo-callback")
async def twilio_demo_callback(request: Request) -> Response:
    form = await request.form()
    speech = (form.get("SpeechResult") or "").lower()
    digit = (form.get("Digits") or "").strip()
    frm = form.get("From") or form.get("Caller") or ""
    yes = digit == "1" or any(w in speech for w in ("yes", "sure", "ok", "okay", "please", "yeah", "yep", "definitely"))
    if yes:
        LEADS.append({"number": frm, "stage": "callback_requested", "speech": speech})
        print(f"[demo-lead] callback requested by {frm!r} :: {speech!r}", flush=True)
        action = escape(f"{PUBLIC_BASE}/api/twilio/demo-lead")
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response>'
                        f'<Gather input="speech" speechTimeout="auto" action="{action}" method="POST">'
                        '<Say>Great. So we can prepare, roughly how many agents or seats are we talking about, '
                        'and what is the main use case?</Say></Gather>'
                        f'<Redirect>{action}</Redirect></Response>', media_type="application/xml")
    print(f"[demo-lead] {frm!r} declined a callback", flush=True)
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response>'
                    '<Say>No problem. Thanks for trying the Sanas demo. Goodbye.</Say><Hangup/></Response>',
                    media_type="application/xml")


@router.post("/api/twilio/demo-lead")
async def twilio_demo_lead(request: Request) -> Response:
    form = await request.form()
    detail = (form.get("SpeechResult") or "").strip()
    frm = form.get("From") or form.get("Caller") or ""
    LEADS.append({"number": frm, "stage": "details", "workload": detail})
    print(f"[demo-lead] details from {frm!r} :: {detail!r}", flush=True)
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response>'
                    '<Say>Thank you. A Sanas specialist will reach out shortly to tailor a plan to your needs. '
                    'Goodbye.</Say><Hangup/></Response>', media_type="application/xml")


@router.websocket("/api/twilio/demo-capture")
async def twilio_demo_capture(ws: WebSocket):
    """Phase 1 — capture the caller's spoken dialog once (8 kHz PCM), ending on a
    spoken 'done' (faster-whisper), trailing silence, a keypad press, or a ~32s cap.
    Stores it on DEMO[call_sid]['pcm'] for the playback phase."""
    import asyncio
    try: import asr
    except Exception: asr = None
    await ws.accept()
    loop = asyncio.get_running_loop()
    call_sid = None
    pcm: list = []                 # int16 @ 8k
    busy = {"v": False}; end = {"reason": None}
    frames = spoke = silence = 0
    MAX, SILENCE_HOLD, CMD_EVERY = 1600, 140, 110   # ~32s cap, ~2.8s trailing silence, ~2.2s ASR cadence
    END_WORDS = ("done", "i'm done", "im done", "that's it", "thats it", "that is it",
                 "that's all", "thats all", "finished", "i'm finished", "go ahead",
                 "ready", "stop", "okay done", "ok done", "next")

    async def check_done(samples):
        if busy["v"] or not (asr and asr.available()):
            return
        busy["v"] = True
        try:
            res = await loop.run_in_executor(None, asr.transcribe, samples, TW_SR)
            txt = ((res or {}).get("text") or "").strip().lower()
            if txt:
                print(f"[demo-capture] heard: {txt!r}", flush=True)
            if any(w in txt for w in END_WORDS):
                end["reason"] = "spoken"
        except Exception as e:
            print(f"[demo-capture] asr error: {e}", flush=True)
        finally:
            busy["v"] = False

    print(f"[demo-capture] connected (asr={'on' if (asr and asr.available()) else 'off'})", flush=True)
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            ev = msg.get("event")
            if ev == "start":
                call_sid = msg["start"].get("callSid") or msg["start"]["streamSid"]
            elif ev == "dtmf":
                if (msg.get("dtmf") or {}).get("digit") in ("#", "1", "0"):
                    end["reason"] = "keypad"
            elif ev == "media":
                if not _AUDIOOP:
                    continue
                ints = np.frombuffer(audioop.ulaw2lin(base64.b64decode(msg["media"]["payload"]), 2), dtype=np.int16)
                pcm.append(ints)
                frames += 1
                amp = int(np.abs(ints.astype(np.int32)).mean()) if ints.size else 0
                if amp > 350:
                    spoke += 1; silence = 0
                elif spoke > 25:
                    silence += 1
                # rolling ASR over the last ~5s (kept, not discarded — so 'done' is never lost mid-transcribe)
                if asr and asr.available() and frames % CMD_EVERY == 0 and not busy["v"] and pcm:
                    snap = np.concatenate(pcm)[-TW_SR * 5:]
                    asyncio.create_task(check_done(snap))
                if not end["reason"]:
                    if frames >= MAX: end["reason"] = "cap"
                    elif spoke > 50 and silence >= SILENCE_HOLD: end["reason"] = "silence"
                if end["reason"]:
                    break
            elif ev == "stop":
                end["reason"] = end["reason"] or "hangup"
                break
    except WebSocketDisconnect:
        end["reason"] = end["reason"] or "disconnect"
    except Exception as e:
        print(f"[demo-capture] error: {e}", flush=True)
    finally:
        buf = np.concatenate(pcm) if pcm else np.zeros(0, dtype=np.int16)
        if call_sid:
            DEMO.setdefault(call_sid, {})["pcm"] = buf.astype(np.int16).tobytes()   # int16 @ 8k
        print(f"[demo-capture] end ({end['reason']}) · {frames} frames · {round(len(buf)/TW_SR,1)}s captured", flush=True)


@router.websocket("/api/twilio/demo-play-ws")
async def twilio_demo_play_ws(ws: WebSocket):
    """Phase 2 — replay the captured dialog through one model (or 'raw'), in real time,
    to the caller. Streams 20 ms μ-law frames; a keypad press skips to the next item."""
    import asyncio
    await ws.accept()
    loop = asyncio.get_running_loop()
    model = ws.query_params.get("model") or SANAS_MODEL
    stream_sid = call_sid = None
    skip = {"v": False}
    try:
        while True:                                 # wait for start to learn the stream + call
            msg = json.loads(await ws.receive_text())
            if msg.get("event") == "start":
                cp = msg["start"].get("customParameters") or {}
                model = cp.get("model") or model
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid") or stream_sid
                break
            if msg.get("event") == "stop":
                return
        raw = DEMO.get(call_sid, {}).get("pcm")
        if not raw or not _AUDIOOP:
            print(f"[demo-play] model={model}: no captured audio for call (raw={bool(raw)}, audioop={_AUDIOOP}) — nothing to play", flush=True)
            return
        buf = np.frombuffer(raw, dtype=np.int16)
        print(f"[demo-play] model={model} · replaying {round(len(buf)/TW_SR,1)}s", flush=True)

        async def reader():                          # keypad → skip to next item
            try:
                while True:
                    m = json.loads(await ws.receive_text())
                    if m.get("event") == "stop" or (m.get("event") == "dtmf" and (m.get("dtmf") or {}).get("digit") in ("1", "#", "0")):
                        skip["v"] = True
            except Exception:
                skip["v"] = True
        rtask = asyncio.create_task(reader())

        async def send8k(frame_int16):
            payload = base64.b64encode(audioop.lin2ulaw(frame_int16.astype(np.int16).tobytes(), 2)).decode()
            await ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}))

        if model == "raw" or sanas_client.client.mode != "real":
            for off in range(0, len(buf), 160):       # play the original at real time
                if skip["v"]: break
                await send8k(buf[off:off + 160]); await asyncio.sleep(0.02)
        else:
            msr = sanas_client.MODEL_SAMPLE_RATES.get(model, 16000)
            up, _st = audioop.ratecv(buf.tobytes(), 2, 1, TW_SR, msr, None)
            floats = np.frombuffer(up, dtype=np.int16).astype(np.float32) / 32768.0
            sess = None
            try:
                sess = await loop.run_in_executor(None, sanas_client.client.create_stream, model, msr)
                fr = sess.frame_samples
            except Exception as e:
                print(f"[demo-play] {model}: create_stream failed: {e}", flush=True)
                sess = None
            if sess is None:                          # fall back to the raw clip so something plays
                print(f"[demo-play] {model}: no session — playing raw fallback", flush=True)
                for off in range(0, len(buf), 160):
                    if skip["v"]: break
                    await send8k(buf[off:off + 160]); await asyncio.sleep(0.02)
            else:
                down_state = None; sent = 0; err = None; nframes = len(floats) // fr
                for i in range(nframes):              # process + stream one model frame at a time
                    if skip["v"]: break
                    try:
                        out = await loop.run_in_executor(None, sess.process, floats[i * fr:(i + 1) * fr].tolist())
                    except Exception as e:
                        err = err or e; out = []
                    if out:
                        arr = (np.clip(np.asarray(out, dtype=np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)
                        down, down_state = audioop.ratecv(arr.tobytes(), 2, 1, msr, TW_SR, down_state)
                        d = np.frombuffer(down, dtype=np.int16)
                        if d.size:
                            await send8k(d); sent += int(d.size)
                    await asyncio.sleep(0.02)
                try: await loop.run_in_executor(None, sess.close)
                except Exception: pass
                print(f"[demo-play] {model}: sent {round(sent / TW_SR, 1)}s of audio from {nframes} frames"
                      + (f" · process err={err}" if err else ""), flush=True)
        rtask.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[demo-play] error: {e}", flush=True)


# ---- Voice access token for the browser SDK (hand-signed JWT) ---------------
def _voice_token(identity: str, push_credential_sid: str | None = None) -> str:
    now = int(time.time())
    header = {"typ": "JWT", "alg": "HS256", "cty": "twilio-fpa;v=1"}
    voice = {"outgoing": {"application_sid": APP_SID}, "incoming": {"allow": True}}
    if push_credential_sid:
        # ring incoming / app-to-app calls on the registered mobile device
        voice["push_credential_sid"] = push_credential_sid
    grants = {"identity": identity, "voice": voice}
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
    """Mid-call control for an in-path call (single-leg media by call_sid, or in-path
    bridge by bridge_id): flip Sanas on/off (`enabled`) and/or switch the active model
    (`model`) live. Switching a model recreates the processor without dropping the call."""
    import asyncio
    d = await request.json()
    model = (d.get("model") or "").strip() or None
    bridge_id = (d.get("bridge_id") or "").strip()
    call_sid = (d.get("call_sid") or "").strip()
    if bridge_id:
        entry = BRIDGES.setdefault(bridge_id, {"enabled": True})
    elif call_sid:
        entry = STREAMS.setdefault(call_sid, {"enabled": True})
    else:
        return JSONResponse({"ok": False, "detail": "call_sid or bridge_id required"}, status_code=400)
    if "enabled" in d:
        entry["enabled"] = bool(d.get("enabled"))
    if model and model != entry.get("model"):
        entry["enabled"] = True                       # picking a model implies Sanas on
        await _set_model(entry, model, asyncio.get_running_loop())
    return JSONResponse({"ok": True, "bridge_id": bridge_id or None, "call_sid": call_sid or None,
                         "enabled": entry.get("enabled", True), "model": entry.get("model")})


@router.get("/api/twilio/debug")
def twilio_debug() -> JSONResponse:
    """Live snapshot of in-flight call state — poll while a call is up to see whether
    BOTH legs joined, the active model, and whether Sanas is on. (No audio is exposed.)
    For a bridge call you want caller_joined AND callee_joined to be true; if only the
    caller joined, the dialed party never connected (the 'in call, no audio' symptom)."""
    def _b(b: dict) -> dict:
        return {"enabled": b.get("enabled"), "model": b.get("model"), "to": b.get("to"),
                "caller_joined": b.get("caller") is not None,
                "callee_joined": b.get("callee") is not None,
                "sanas_session": b.get("sess") is not None}
    return JSONResponse({
        "sanas_mode": sanas_client.client.mode,
        "bridges": {k: _b(v) for k, v in BRIDGES.items()},
        "streams": {k: {"enabled": v.get("enabled")} for k, v in STREAMS.items()},
        "leads": LEADS[-20:][::-1],   # guided-demo callback requests, newest first
    })


_IDENTITY_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


@router.get("/api/twilio/token")
def twilio_token(request: Request, _a: str | None = Depends(auth.require_sani_auth)) -> JSONResponse:
    # _a: enforces a valid @<domain> session bearer when SANI_AUTH_REQUIRED is on;
    # a no-op otherwise (web app + unauthenticated mobile keep working).
    if not _cfg()["browser_voice"]:
        return JSONResponse({"ok": False, "detail": "Browser/mobile voice not configured "
                             "(need TWILIO_ACCOUNT_SID + API key/secret + TWIML_APP_SID)."}, status_code=200)
    # A mobile client may request a STABLE identity so it can be dialed app-to-app;
    # otherwise mint an ephemeral one. Sanitize to Twilio's client-name charset.
    raw = (request.query_params.get("identity") or "").strip()
    identity = "".join(c for c in raw if c in _IDENTITY_OK)[:121] or f"sani-{int(time.time())}"
    push = _push_cred_for(request.query_params.get("platform"))
    return JSONResponse({"ok": True, "token": _voice_token(identity, push),
                         "identity": identity, "push": bool(push)})


# ---- Media Streams WS: call audio → Sanas → back into the call --------------
@router.websocket("/api/twilio/media")
async def twilio_media(ws: WebSocket):
    import asyncio
    await ws.accept()
    loop = asyncio.get_running_loop()
    model = ws.query_params.get("model") or SANAS_MODEL     # fallback; real value in customParameters
    stream_sid = None
    call_sid = None
    entry = None

    try:
        while True:
            raw = await ws.receive_text()           # Twilio sends JSON text frames
            msg = json.loads(raw)
            ev = msg.get("event")
            if ev == "start":
                model = (msg["start"].get("customParameters") or {}).get("model") or model
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid") or stream_sid
                # Shared session state (sess/up/down/resid/enabled/model) so /api/twilio/
                # toggle can flip Sanas on/off AND switch the model live, mid-call.
                entry = STREAMS.setdefault(call_sid, {"enabled": True})
                entry["stream_sid"] = stream_sid
                await _set_model(entry, model, loop)   # opens the processor at the model's native rate
            elif ev == "media":
                if entry is None:                       # no start yet — echo raw
                    await ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid,
                                                    "media": {"payload": msg["media"]["payload"]}}))
                    continue
                # _process_caller handles resampling + on/off; returns raw payload when
                # Sanas is off/unavailable, the processed payload, or None while buffering.
                try:
                    out = await loop.run_in_executor(None, _process_caller, entry, msg["media"]["payload"])
                except Exception:
                    out = msg["media"]["payload"]       # never drop the call on a transient (mid model-switch)
                if out is None:
                    continue
                await ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid,
                                               "media": {"payload": out}}))
            elif ev == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if call_sid and call_sid in STREAMS:
            sess = STREAMS[call_sid].get("sess")
            if sess is not None:
                try: await loop.run_in_executor(None, sess.close)
                except Exception: pass
            STREAMS.pop(call_sid, None)


def _open_sess(model: str):
    return sanas_client.client.create_stream(model, sanas_client.MODEL_SAMPLE_RATES.get(model, TW_SR))


async def _set_model(entry: dict, model: str, loop) -> None:
    """Switch the live Sanas model on a STREAMS/BRIDGES entry mid-call: close the old
    processor and open the new one at the model's native rate, resetting resample
    state. The media/bridge loops read entry['sess'] each frame and pass raw audio
    through during the brief swap, so the call is never dropped."""
    if not model:
        return
    old = entry.get("sess")
    entry["sess"] = None
    if old is not None:
        try: await loop.run_in_executor(None, old.close)
        except Exception: pass
    entry["up"] = entry["down"] = None
    entry["resid"] = None
    entry["model"] = model
    if sanas_client.client.mode == "real" and _AUDIOOP:
        try:
            entry["sess"] = await loop.run_in_executor(None, _open_sess, model)
        except Exception:
            entry["sess"] = None


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
    # Twilio strips the wss query string, so these are only a fallback — the real
    # values arrive in the 'start' event's customParameters (set below).
    bid = qp.get("id") or ""
    role = qp.get("role") or "caller"
    model = qp.get("model") or SANAS_MODEL
    to = qp.get("to")
    br = None
    stream_sid = None
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            ev = msg.get("event")
            if ev != "start" and br is None:
                continue                              # ignore media/dtmf before start
            if ev == "start":
                cp = msg["start"].get("customParameters") or {}
                bid = cp.get("id") or bid
                role = cp.get("role") or role
                model = cp.get("model") or model
                to = cp.get("to") or to
                br = BRIDGES.setdefault(bid, {"enabled": True})
                stream_sid = msg["start"]["streamSid"]
                br[role] = ws
                br[f"{role}_sid"] = stream_sid
                print(f"[bridge {bid}] {role} stream started", flush=True)
                if role == "caller":
                    br.setdefault("enabled", True)
                    br["model"] = model
                    br["to"] = to
                    br["up"] = br["down"] = None
                    br["resid"] = None
                    br["caller_call_sid"] = msg["start"].get("callSid")
                    print(f"[bridge {bid}] caller joined · to={to!r} · model={model} "
                          f"· phone_callback={_cfg()['phone_callback']}", flush=True)
                    if sanas_client.client.mode == "real" and _AUDIOOP:
                        try:
                            br["sess"] = await loop.run_in_executor(None, _open_sess, model)
                            print(f"[bridge {bid}] sanas session opened ({model})", flush=True)
                        except Exception as e:
                            br["sess"] = None
                            print(f"[bridge {bid}] sanas session FAILED: {e}", flush=True)
                    # dial the person; their leg streams back as role=callee
                    if to and _cfg()["phone_callback"]:
                        url = f"{PUBLIC_BASE}/api/twilio/voice?mode=bridgeleg&id={urllib.parse.quote(bid)}&model={urllib.parse.quote(model)}"
                        try:
                            res = await loop.run_in_executor(None, _create_call, to, url)
                            print(f"[bridge {bid}] dialing callee {to} → "
                                  f"sid={res.get('sid')} status={res.get('status')}", flush=True)
                        except Exception as e:
                            print(f"[bridge {bid}] callee dial FAILED: {e}", flush=True)
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
