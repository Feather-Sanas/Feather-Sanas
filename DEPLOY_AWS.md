# Deploying Sani on AWS — single-instance demo

> ## Hosting the front-end on AWS Amplify (the split)
> **Amplify Hosting can serve the front-end, but not the backend.** Amplify is
> serverless (static sites + SSR + Lambda); this backend needs a long-running process
> (native Sanas SDK SIP/RTP, WebSockets, in-memory call state). So:
>
> - **Front-end → Amplify Hosting.** Connect the GitHub repo; Amplify uses
>   [`amplify.yml`](amplify.yml), which publishes only `index.html` / `app.js` /
>   `styles.css` / `config.js` (never the `server/` source) and bakes the backend
>   origin into `config.js` from the **`SAN_API_BASE`** env var. Set
>   `SAN_API_BASE = https://api.your-domain.com` in the Amplify console → App settings →
>   Environment variables. (No build framework; it's a plain static deploy.)
> - **Backend → a long-running host** (below): EC2 with `docker-compose`, or
>   **App Runner / ECS Fargate** from [`server/Dockerfile`](server/Dockerfile). CORS is
>   already open (`allow_origins=["*"]`), so the Amplify origin reaches it; the live-mic
>   and Twilio WebSockets connect to `wss://<SAN_API_BASE host>` automatically.
> - **Twilio** `PUBLIC_BASE_URL` + the TwiML App Voice URL must point at the **backend**
>   origin (not the Amplify URL) — browser calling dials the backend's `/api/twilio/*`.
>
> If you'd rather keep it simple, skip Amplify and serve the front-end from the same
> EC2 box (the backend already serves the three files) — one origin, `SAN_API_BASE` empty.

A cost-minimized deploy for a **demo that does not scale**: one EC2 instance running
the backend behind **Caddy** (automatic HTTPS). No load balancer, no NAT gateway, no
Fargate — those only matter for scaling and are the expensive line items.

```
Route 53 (your domain) ──► Elastic IP ──► EC2 (public subnet, x86-64)
                                            └── Docker Compose:
                                                  caddy  (:80/:443, auto-TLS)
                                                    └─► san (uvicorn :8000)
                                                          └─► Sanas SDK · Claude · Twilio
```

## Why this shape (not Lambda / Fargate)
The app needs a long-running process: the **native Sanas SDK** holds SIP/RTP
sessions, **WebSockets** carry live mic + Twilio media, and session state is
in-memory. A single container host is the cheapest thing that satisfies all three.
**One instance only** — a redeploy or restart drops in-flight live/bridge sessions
(acceptable for a demo).

## Cost (us-east-1, on-demand)
| Item | ~Monthly |
|---|---|
| EC2 `t3.small` (2 vCPU / 2 GB) running 24/7 | ~$15 |
| EBS 20 GB gp3 | ~$1.60 |
| Elastic IP (one, attached) | ~$3.60 |
| Route 53 hosted zone | $0.50 (+ domain registration) |
| **Total 24/7** | **~$21/mo** |

**Stop the instance when not demoing** → you pay only EBS + IP (~$5/mo); it's back
in ~30s on the same URL. faster-whisper (ASR/WER on uploads) is memory-hungry — on
`t3.small` either accept that it's tight, set `SAN_LLM`-side `ASR` off, or use
`t3.medium` (4 GB, ~$30/mo). Everything else fits in 2 GB.

---

## Prerequisites
- **The Linux x86-64 Sanas SDK tarball** (`sanas_remote_sdk_linux_x86-64_<ver>.tar.gz`).
  Without it the container runs in **mock mode** (no real Sanas processing). The
  macOS wheel you have locally will not work on the Linux box.
- A registered domain you can point at the instance (for HTTPS + stable Twilio URLs).
- Your filled-in `server/.env` (never committed).

## 1. Launch the instance
- AMI: Ubuntu 22.04 or Amazon Linux 2023, **architecture x86-64** (not Graviton — the
  SDK is x86-64).
- Type: `t3.small` (or `t3.medium` to keep ASR comfortable).
- Storage: 20 GB gp3.
- Allocate an **Elastic IP** and associate it (keeps the URL stable across stop/start).
- **Security group** inbound: `443` and `80` from `0.0.0.0/0`; `22` from **your IP only**.
  Outbound: leave default allow-all (needed for Claude, the Sanas SIP/RTP endpoint, and Twilio).

## 2. DNS
In Route 53 (or your registrar), create an **A record** for `sani.example.com` → the
Elastic IP. Wait for it to resolve before step 5 (Caddy needs it to issue the cert).

## 3. Install Docker + Compose on the box
```bash
ssh ubuntu@<elastic-ip>
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER && newgrp docker      # so docker runs without sudo
```

## 4. Get the code + secrets + SDK onto the box
```bash
git clone https://github.com/Feather-Sanas/Feather-Sanas.git sani && cd sani

# Secrets — copy your filled-in env up from your laptop (do NOT commit it):
#   scp server/.env  ubuntu@<elastic-ip>:~/sani/server/.env
chmod 600 server/.env

# Linux SDK tarball into the build context:
#   scp sanas_remote_sdk_linux_x86-64_<ver>.tar.gz  ubuntu@<elastic-ip>:~/sani/server/vendor/
```

In `server/.env`, set the public base to your domain:
```ini
PUBLIC_BASE_URL=https://sani.example.com
```

## 5. Bring it up (Caddy auto-issues the TLS cert)
```bash
SITE_ADDRESS=sani.example.com docker compose up -d --build
```
`SITE_ADDRESS` is the **bare domain** (Caddy/cert); `PUBLIC_BASE_URL` is the **https URL**
(the app, for TwiML + `wss://`). Verify:
```bash
curl -s https://sani.example.com/api/health | python3 -m json.tool   # mode:"real", sdk_available:true
docker compose logs -f caddy                                          # watch cert issuance
```
Tip: persist `SITE_ADDRESS` so restarts don't need it inline — add `SITE_ADDRESS=sani.example.com`
to a root-level `.env` (Compose auto-loads it for variable substitution).

## 6. Point Twilio at the new domain (replaces ngrok)
With the box live at `https://sani.example.com`:
```bash
cd server && set -a && . ./.env && set +a
# Number's Voice webhook:
curl -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers/<PN_SID>.json" \
  --data-urlencode "VoiceUrl=$PUBLIC_BASE_URL/api/twilio/voice" --data-urlencode "VoiceMethod=POST"
# TwiML App Voice URL (browser voice):
curl -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Applications/$TWILIO_TWIML_APP_SID.json" \
  --data-urlencode "VoiceUrl=$PUBLIC_BASE_URL/api/twilio/voice" --data-urlencode "VoiceMethod=POST"
```
A real domain means you set this **once** — no more per-session re-pointing. See
[TWILIO_SETUP.md](TWILIO_SETUP.md) for the full telephony checklist.

---

## Day-2 operations
| Task | Command |
|---|---|
| Update to latest | `git pull && SITE_ADDRESS=sani.example.com docker compose up -d --build` |
| Logs | `docker compose logs -f san` / `... caddy` |
| Restart | `docker compose restart san` |
| **Stop to save money** | `docker compose down` then **Stop** the instance in the EC2 console |
| Resume | **Start** the instance; Compose comes back via `restart: unless-stopped` (or `up -d`) |

## Notes & limits
- **Single instance / in-memory state** — live mic and Twilio bridge sessions don't
  survive a restart or redeploy. Fine for demos; production would need sticky sessions
  + a shared session store.
- **Build is emulated on the box?** No — the EC2 host is x86-64, so the `linux/amd64`
  image builds natively and fast (unlike on an Apple-Silicon laptop).
- **Secrets** stay in `server/.env` on the box (mode 600). For anything beyond a demo,
  move them to AWS Secrets Manager / SSM and inject via the task environment.
- **Mock mode** is the tell that the SDK tarball is missing or failed to install —
  `/api/health` shows `mode:"mock"`. Re-check `server/vendor/` and rebuild.
