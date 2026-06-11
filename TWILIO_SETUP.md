# Twilio voice handoff — go-live setup

Sani can connect a caller to a **human** or an **IVR**, and route the call audio
through the **Sanas telephony model** (`AGENTIC_VI_GT_NC`, 8 kHz) in real time —
with a **mid-call On/Off toggle** to A/B Sanas against the raw line.

The integration is built and verified at the protocol level. To make real calls
you need a public URL + a few Twilio objects. This is the checklist.

---

## The two paths (pick based on your credentials)

| Path | What it needs | Works with **test** creds? |
|---|---|---|
| **Browser voice** (talk in the page, WebRTC) | API Key **SID + Secret**, a **TwiML App**, a public URL | ✅ yes — uses an access token, not the REST Auth Token |
| **Phone callback** (Twilio dials your phone) | Account SID + **Auth Token**, a Twilio number, a public URL | ❌ **no** — test creds can't place real calls; needs **live** Account SID + Auth Token |

> **Recommended for a self-contained demo:** the **browser voice** path — no real
> phone needed, and it doesn't require the live REST Auth Token.

---

## Steps

### 1. Public URL (tunnel to the backend on :8000)
Twilio must reach your TwiML and the Media-Streams `wss`. Either:
```bash
# Option A — ngrok (stable, needs a free authtoken)
ngrok http 8000                      # → https://<id>.ngrok-free.app

# Option B — cloudflared quick tunnel (no account)
cloudflared tunnel --url http://localhost:8000   # → https://<random>.trycloudflare.com
```
Copy the https URL → this is `PUBLIC_BASE_URL`.
> ⚠️ This exposes the backend publicly (it has no per-endpoint auth). The URL is
> unguessable; still, stop the tunnel when you're done, and don't share the URL.

### 2. New API key + secret  (the old secret is unrecoverable)
Console → **Account → API keys & tokens → Create API key** (Standard).
Copy the **Secret immediately** (shown once).
→ `TWILIO_API_KEY_SID` (`SK…`) and `TWILIO_API_KEY_SECRET`.
(You can delete the old key `SKf7a5…` — its secret is gone.)

### 3. Create a TwiML App
Console → **Voice → Manage → TwiML Apps → Create new TwiML App**.
- **Voice Request URL:** `https://<PUBLIC_BASE_URL>/api/twilio/voice`  (method **POST**)
- Save → copy the **App SID** (`AP…`) → `TWILIO_TWIML_APP_SID`.

### 4. Point the number's Voice webhook (for inbound calls)
Console → **Phone Numbers → your number (+1 855 257 0843) → Voice Configuration**.
- **A call comes in:** Webhook → `https://<PUBLIC_BASE_URL>/api/twilio/voice` (POST).
- (This replaces the placeholder `https://demo.twilio.com/welcome/voice/`.)

### 5. Fill `server/.env` and restart
```ini
PUBLIC_BASE_URL=https://<your-tunnel>
TWILIO_ACCOUNT_SID=AC…          # LIVE SID for phone callback; test SID is fine for browser voice
TWILIO_AUTH_TOKEN=…             # LIVE Auth Token only needed for phone callback
TWILIO_NUMBER=+18552570843
TWILIO_HUMAN_NUMBER=+18552570843
TWILIO_API_KEY_SID=SK…
TWILIO_API_KEY_SECRET=…         # from step 2
TWILIO_TWIML_APP_SID=AP…        # from step 3
TWILIO_SANAS_MODEL=AGENTIC_VI_GT_NC
```
Restart: `cd server && .venv310/bin/uvicorn main:app --port 8000`

### 6. Verify
```bash
curl -s http://127.0.0.1:8000/api/twilio/config | python3 -m json.tool
# browser_voice:true (after steps 2–3); phone_callback:true needs live creds + PUBLIC_BASE_URL
```
In the app: Sani → "talk to someone" → **Connect by voice**:
- **Talk in the browser** → in-page call; Sanas enhances the line.
- **Speak to the IVR / Hear Sanas on the call** → phone callback (live creds).
- Once connected, **Sanas on the call: Model ON/OFF** flips processing live.

---

## How it's wired (for reference)
- `POST /api/twilio/call` — REST click-to-call (urllib + basic auth).
- `GET/POST /api/twilio/voice?mode=ivr|human|sanas` — returns TwiML.
- `POST /api/twilio/gather` — IVR digit routing (1 = human, 2 = Sanas demo).
- `GET /api/twilio/token` — hand-signed Voice access token for the browser SDK.
- `WS /api/twilio/media` — Twilio Media Streams: μ-law 8 kHz → Sanas `ProcessSamples` → back.
- `POST /api/twilio/toggle {call_sid, enabled}` — mid-call model On/Off.

All endpoints degrade gracefully when unconfigured (`/api/twilio/config` reports what's live).
