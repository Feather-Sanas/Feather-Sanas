# Twilio voice handoff — go-live setup

Sani connects a caller to a **human** or bridges two parties, and routes the call
audio through **Sanas** in real time. Three ways to use it, all with a **mid-call
model On/Off** (and live model switching):

1. **Dial-in (recommended demo of in-path Sanas):** call your Twilio number, key in
   a destination, and you're bridged two-way — your voice is **cleaned by Sanas
   before the other person hears it**. Press keys mid-call to switch models.
2. **Browser voice:** talk in the page (WebRTC). Blank number = hear yourself
   through Sanas; enter a number = call them (optionally Sanas **in-path**, beta).
3. **Phone callback:** Twilio dials your phone and runs the IVR / Sanas demo.

The integration is built and verified at the protocol level with the real Sanas
engine. To make real calls you need a public URL + a few Twilio objects.

---

## ⚠️ Trial accounts can only dial *verified* numbers

This is the single most common surprise. On a **Trial** Twilio account, every outbound
or bridged leg may only reach a number that has been added as a **Verified Caller ID**.
Dialling anything else fails with **error 21219** — the dial-in flow will appear to
"only let you call one number" (the verified one).

> Current project account `AC2417…dfa6` is **type: Trial**, with a single verified
> number: **+1 801-850-3440**. That's why the dial-in bridge only connects to it.
>
> Check anytime:
> ```bash
> cd server && set -a && . ./.env && set +a
> curl -s -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
>   "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID.json" \
>   | python3 -c "import sys,json;d=json.load(sys.stdin);print('type:',d['type'])"   # Trial | Full
> ```

**Fix:** upgrade the account, or verify each destination number — see
[Lifting the trial restriction](#lifting-the-trial-restriction) below. Inbound (you
calling *into* the Twilio number) always works on trial.

---

## What each path needs

| Path | Needs | Works with **test** creds? |
|---|---|---|
| **Dial-in / bridge** | a Twilio number + **live** Account SID + Auth Token + public URL | ❌ outbound leg needs **live** creds (+ destination verified on trial) |
| **Browser voice** | API Key **SID + Secret**, a **TwiML App**, public URL | ✅ uses an access token, not the REST Auth Token |
| **Phone callback** | live Account SID + Auth Token, a number, public URL | ❌ test creds can't place real calls |

---

## Steps

### 1. Public URL (tunnel to the backend on :8000)
Twilio must reach your TwiML and the Media-Streams `wss`:
```bash
ngrok http 8000                      # → https://<id>.ngrok-free.dev   (stable; needs a free authtoken)
# or: cloudflared tunnel --url http://localhost:8000   (no account; can be flaky)
```
Copy the https URL → `PUBLIC_BASE_URL`.
> ⚠️ This exposes the backend publicly (no per-endpoint auth). Stop the tunnel when done.
> ngrok's free URL changes per session — re-point the TwiML App + number webhook if it does.

### 2. API key + secret  (secret shown once)
Console → **Account → API keys & tokens → Create API key** (Standard) →
`TWILIO_API_KEY_SID` (`SK…`) + `TWILIO_API_KEY_SECRET`.

### 3. Create a TwiML App (for browser voice)
Console → **Voice → Manage → TwiML Apps → Create** →
- **Voice Request URL:** `https://<PUBLIC_BASE_URL>/api/twilio/voice`  (POST)
- Save → copy **App SID** (`AP…`) → `TWILIO_TWIML_APP_SID`.

### 4. Point the number's Voice webhook (for dial-in / inbound)
Console → **Phone Numbers → (425) 842-0002 → Voice Configuration → A call comes in:**
- Webhook → `https://<PUBLIC_BASE_URL>/api/twilio/voice` (POST).

With live creds you can set this via API instead:
```bash
curl -u "$SID:$LIVE_TOKEN" -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$SID/IncomingPhoneNumbers/<PN_SID>.json" \
  --data-urlencode "VoiceUrl=https://<PUBLIC_BASE_URL>/api/twilio/voice" --data-urlencode "VoiceMethod=POST"
```

### 5. Fill `server/.env` and restart
```ini
PUBLIC_BASE_URL=https://<your-tunnel>
TWILIO_ACCOUNT_SID=AC…          # LIVE SID for dial-in/callback (browser voice tolerates either)
TWILIO_AUTH_TOKEN=…             # LIVE Auth Token (dial-in/callback)
TWILIO_NUMBER=+14258420002
TWILIO_HUMAN_NUMBER=+1…         # a real human line for "talk to a human" (not the Twilio number)
TWILIO_API_KEY_SID=SK…
TWILIO_API_KEY_SECRET=…
TWILIO_TWIML_APP_SID=AP…
TWILIO_SANAS_MODEL=AGENTIC_VI_GT_NC   # 8 kHz telephony model (default on the call)
```
Restart: `cd server && .venv310/bin/uvicorn main:app --port 8000`

### 6. Verify
```bash
curl -s http://127.0.0.1:8000/api/twilio/config | python3 -m json.tool
```

---

## Using the dial-in flow

1. Call **(425) 842-0002**.
2. "Enter the number you'd like to call, with country code, then press #." → key it, press #.
   (10 digits → assumed US `+1`; otherwise it prefixes `+`.)
3. You're bridged two-way; **your voice is cleaned by Sanas in-path** before the callee hears it.
4. **Press keys mid-call** to switch live (each plays a short confirmation tone):
   - **1** → Noise Cancellation (`AGENTIC_VI_GT_NC`, 8 kHz)
   - **2** → Speech Enhancement (`SE2.2`, 16 kHz, auto-resampled to the line)
   - **3** → Voice Isolation (`VI_G_NC3.0`, 16 kHz)
   - **0** → Sanas off (raw line)

> **Trial limit:** the dialed destination must be a **Verified Caller ID** (error 21219)
> or the account upgraded — see below. Inbound (you calling in) works on trial.

---

## Lifting the trial restriction

Two options:

### Option A — Upgrade the account (recommended; removes the limit entirely)
Console → **Admin / Billing → Upgrade**, add a payment method. A full account can dial
**any** number; no per-number verification needed. (Billing details are yours to enter —
this can't be done via the API.) After upgrading, re-check `type: Full` with the command
in the trial callout above. Nothing in `server/.env` changes — the same SID/token now
work without the restriction.

### Option B — Verify specific destination numbers (stay on the free trial)
Each number you want to reach must complete a one-time verification (Twilio calls it and
reads a 6-digit code the recipient enters). Do it in the console
(**Phone Numbers → Verified Caller IDs → Add**) or via the API:

```bash
cd server && set -a && . ./.env && set +a
# 1) start verification — Twilio calls the number and speaks a 6-digit code
curl -s -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/OutgoingCallerIds.json" \
  --data-urlencode "PhoneNumber=+1XXXXXXXXXX" --data-urlencode "FriendlyName=demo dest"
#    → the call states a ValidationCode; the recipient keys it into the phone to confirm.
# 2) list verified numbers (confirm it stuck)
curl -s -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/OutgoingCallerIds.json" \
  | python3 -c "import sys,json;[print(' ',c['phone_number']) for c in json.load(sys.stdin)['outgoing_caller_ids']]"
```
Trial calls also play a short "trial account" preamble before connecting — that goes away
on upgrade too.

---

## How it's wired (reference)

- `GET/POST /api/twilio/voice` — TwiML. No mode (inbound) → **dial-in prompt**; `mode=ivr|human|sanas|dial|bridge|bridgeleg`.
- `POST /api/twilio/dialin-connect` — gathers the keyed number → bridges via `<Connect><Stream>`.
- `WS /api/twilio/bridge` — joins **caller** + **callee** legs; caller audio → Sanas → callee; relays callee → caller; reads **DTMF** to switch model / toggle; injects confirmation tones. Resamples 8 kHz ↔ 16 kHz models.
- `WS /api/twilio/media` — single-leg Media Stream: μ-law 8 kHz → Sanas `ProcessSamples` → back.
- `POST /api/twilio/toggle {call_sid|bridge_id, enabled}` — mid-call On/Off.
- `POST /api/twilio/call` — REST click-to-call.  `GET /api/twilio/token` — browser Voice access token.

All endpoints degrade gracefully when unconfigured (`/api/twilio/config` reports what's live).
