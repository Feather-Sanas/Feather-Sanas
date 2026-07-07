# Deploying Sanas.AI on AWS

This is the production reference for running Sanas.AI on AWS. It has two layers:

- **Demo baseline** — one EC2 instance behind Caddy. Cheapest thing that runs every
  feature (native Sanas SDK, WebSockets, Claude, Twilio). Start here.
- **Production hardening / scale** — Amplify for the front-end, Secrets Manager for
  credentials, SES for the book-a-demo email, ElastiCache (Redis) for the shared
  response cache + rate limiter, and a managed-services path (App Runner / ECS Fargate)
  when one box isn't enough. Layered on top of the baseline; adopt the pieces you need.

> **The backend is x86-64 only.** The Sanas Remote SDK is a native x86-64 binary — every
> backend host (EC2, Fargate, App Runner) must be **x86-64 / linux/amd64**, never Graviton
> (arm64). The front-end is static and architecture-agnostic.

> **Two ways to run this:**
> - **Terraform (recommended — automated).** [`infra/aws/`](infra/aws/) provisions the whole
>   stack: VPC + x86-64 EC2 + Elastic IP behind Caddy, Secrets Manager (the `server/.env`),
>   S3 (the Sanas SDK tarball), Route 53 DNS, Amplify (front-end), SES (email), and
>   least-privilege IAM + SSM. Fill in
>   [`infra/aws/terraform.tfvars.example`](infra/aws/terraform.tfvars.example) and follow
>   [`infra/aws/README.md`](infra/aws/README.md). The sections below are the reference for
>   **what that module builds and why.**
> - **By hand.** The step-by-step runbook in this document (§3 onward) — use it to understand
>   the pieces, or to deploy without Terraform.

---

## 1. The shape, and why

```
                         ┌──────────────────────── AWS ────────────────────────┐
                         │                                                      │
  Browser ──► Route 53 ──┤  ┌─ Amplify Hosting (CloudFront + S3) ──────────┐    │
   (HTTPS)               │  │  index.html · app.js · styles.css · config.js │   │
                         │  │  config.js bakes in SAN_API_BASE = api origin │   │
                         │  └───────────────────────────────────────────────┘   │
                         │                       │ HTTPS/WSS (CORS *)            │
                         │                       ▼                              │
  Twilio ──► Route 53 ──►│   Elastic IP ──► EC2 (x86-64, public subnet)         │
  (webhooks, media WSS)  │                   └── Docker Compose:                │
                         │                         caddy  (:80/:443 auto-TLS)   │
                         │                           └─► san (uvicorn :8000)    │
                         │                                 ├─ Sanas SDK (SIP/RTP)│
                         │                                 ├─ Claude (Anthropic) │
                         │                                 ├─ faster-whisper ASR │
                         │                                 ├─ Twilio REST/Media  │
                         │                                 └─ response cache +   │
                         │                                    rate limit (RAM)   │
                         │   ┌─ optional, for production / scale ────────────┐   │
                         │   │ Secrets Manager · SES (SMTP) · ElastiCache    │   │
                         │   │ (Redis: shared cache + rate limit) · CloudWatch│  │
                         │   └────────────────────────────────────────────────┘  │
                         └──────────────────────────────────────────────────────┘
```

The backend is a **single long-running process** holding things a serverless function
can't: the native Sanas SDK's SIP/RTP sessions, live-mic and Twilio-media **WebSockets**,
and **in-memory state** (admin tokens, demo/partner leads, live-call `STREAMS`/`BRIDGES`,
the response cache, and rate-limit counters). That's why the backend is a container host,
not Lambda. The front-end is just four static files, so it can ride a CDN (Amplify) or be
served by the same backend — your call (§6).

> **One instance = in-memory state is per-process and dies on restart.** A redeploy or
> restart drops in-flight live/bridge calls, logs out admins, and empties the response
> cache and lead lists. Acceptable for a demo. To run more than one backend instance you
> must move that shared state to ElastiCache and add sticky routing for the live-call
> dicts — see §8.

---

## 2. AWS services + the access your IT team must grant

The app makes **no AWS API calls in code** — it talks to Anthropic, Sanas, Twilio, and an
SMTP server over the open internet. So "access" is mostly *network egress* plus the
managed services you opt into. Give IT this list.

### Required (demo baseline)

| Service | Why | Specific access to grant |
|---|---|---|
| **EC2** | Runs the backend container host (x86-64). | Launch a `t3.small`/`t3.medium` (or `c6i`/`m6i`) **x86-64** instance; attach EBS gp3. IAM: `ec2:RunInstances`, `ec2:Describe*`, plus an **instance role** (below). |
| **EBS** | Persists the RAG store (`/data`) and Caddy TLS certs across restarts. | One gp3 volume (root 20 GB is enough); enable snapshots if the uploaded-doc index matters. |
| **Elastic IP** | Stable public IP so the Twilio webhook URL and DNS don't change across stop/start. | `ec2:AllocateAddress` + `AssociateAddress` (1 EIP). |
| **Route 53** (or any DNS) | `A` record → Elastic IP, so Caddy can issue a Let's Encrypt cert and Twilio has a stable HTTPS/WSS origin. | A hosted zone + one `A` record. (External registrars work too.) |
| **VPC security group — outbound** | The backend must reach Anthropic, Sanas, Twilio, SMTP, and (first run) Hugging Face. | **Outbound 443** to `api.anthropic.com`, `api.twilio.com`, Twilio Media Streams, `huggingface.co`; **outbound to `SANAS_ENDPOINT`** (SIP signalling + RTP media — confirm ports with Sanas); **outbound 587/465** to your SMTP host. Default allow-all egress satisfies all of these. |
| **VPC security group — inbound** | Public HTTPS + your SSH. | **443 + 80** from `0.0.0.0/0` (Caddy / cert issuance); **22** from your IP only. |

### Recommended for production

| Service | Why | Specific access to grant |
|---|---|---|
| **Secrets Manager** (or SSM Parameter Store) | Hold `ANTHROPIC_API_KEY`, `SANAS_*`, `TWILIO_*`, `SMTP_*`, `RAG_ADMIN_PASSWORD` instead of a plaintext `.env` on the box. | Create secrets; grant the **EC2 instance role** `secretsmanager:GetSecretValue` (scoped to these secret ARNs) — or `ssm:GetParameters` for SecureString params. |
| **SES** | Production SMTP for the book-a-demo / partner emails (no app password to manage). | Verify a sending domain/identity; create SES **SMTP credentials**; move the account out of the SES sandbox. The app uses SES via plain SMTP (§7) — no IAM call needed at runtime. |
| **ElastiCache (Redis)** | Shared response cache + rate limiter when you run more than one backend instance, and cache survival across restarts. | One small node (e.g. `cache.t4g.micro`); allow the backend SG **outbound 6379** to the cache SG. Point the app at it with `SAN_REDIS_URL` (§5). |
| **CloudWatch Logs** | Capture the container's stdout (call state, model switches, cache fallbacks). | The EC2 instance role needs `logs:CreateLogStream` + `logs:PutLogEvents` (the CloudWatch agent / ECS log driver handles this). |
| **Amplify Hosting** | CDN-served front-end on its own domain. | Connect the GitHub repo; set the `SAN_API_BASE` build env var (§6). Amplify provisions its own CloudFront + S3 — no extra IAM for you. |
| **IAM (instance role)** | The single principal the box assumes. | One EC2 instance role bundling the Secrets Manager **read** + CloudWatch Logs **write** above. **Least privilege: read-only on exactly the secret ARNs, no `*`.** No S3/DynamoDB/RDS permissions are needed — the app doesn't call them. |

> **What you do NOT need:** RDS/DynamoDB (no database in the app), S3 (no object storage in
> the code path), API Gateway (Caddy/ALB front the API directly), or a NAT gateway (the box
> is in a public subnet with an Elastic IP). Adding them is optional future work, not a
> requirement.

---

## 3. Cost (us-east-1, on-demand)

| Item | ~Monthly |
|---|---|
| EC2 `t3.small` (2 vCPU / 2 GB) 24/7 | ~$15 |
| EBS 20 GB gp3 | ~$1.60 |
| Elastic IP (one, attached) | ~$3.60 |
| Route 53 hosted zone | $0.50 (+ domain) |
| **Demo total, 24/7** | **~$21/mo** |
| + Amplify Hosting (low traffic) | ~$0–5/mo |
| + ElastiCache `cache.t4g.micro` (only if scaling) | ~$12/mo |
| + SES | $0.10 / 1,000 emails |

**Stop the instance when not demoing** → you pay only EBS + EIP (~$5/mo); it's back in ~30s
on the same URL. faster-whisper (ASR on uploads) is memory-hungry — `t3.small` is tight; use
`t3.medium` (4 GB, ~$30/mo) if you lean on ASR. The **biggest variable cost is Claude**
(Anthropic API), which §5 is built to contain.

---

## 4. Demo baseline — single EC2 (start here)

### Prerequisites
- **The Linux x86-64 Sanas SDK tarball** (`sanas_remote_sdk_linux_x86-64_<ver>.tar.gz`).
  Without it, audio processing is **unavailable** — `/api/process` returns 503 and the UI
  says so (there is no mock/synthetic processing). The macOS wheel you have locally will not
  work on the Linux box.
- A registered domain you can point at the instance (HTTPS + stable Twilio URLs).
- Your filled-in `server/.env` (never committed) — see [`server/.env.example`](server/.env.example).

### 4.1 Launch the instance
- AMI: Ubuntu 22.04 or Amazon Linux 2023, **architecture x86-64** (not Graviton — the SDK is x86-64).
- Type: `t3.small` (or `t3.medium` to keep ASR comfortable). Storage: 20 GB gp3.
- Allocate an **Elastic IP** and associate it (stable URL across stop/start).
- **Security group** inbound: `443` + `80` from `0.0.0.0/0`; `22` from **your IP only**.
  Outbound: leave default allow-all (Claude, Sanas SIP/RTP, Twilio, SMTP, first-run model download).

### 4.2 DNS
In Route 53 (or your registrar), create an **A record** `sani.example.com` → the Elastic IP.
Wait for it to resolve before §4.5 (Caddy needs it to issue the cert).

### 4.3 Install Docker + Compose
```bash
ssh ubuntu@<elastic-ip>
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER && newgrp docker      # docker without sudo
```

### 4.4 Code + secrets + SDK onto the box
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

### 4.5 Bring it up (Caddy auto-issues the TLS cert)
```bash
SITE_ADDRESS=sani.example.com docker compose up -d --build
```
`SITE_ADDRESS` is the **bare domain** (Caddy/cert); `PUBLIC_BASE_URL` is the **https URL**
(the app, for TwiML + `wss://`). Verify:
```bash
curl -s https://sani.example.com/api/health | python3 -m json.tool
#  -> mode:"real", sdk_available:true, llm_available:true,
#     response_cache:{enabled:true,backend:"memory",...}, rate_limit:{enabled:true,limit:60,...}
docker compose logs -f caddy        # watch cert issuance
```
Tip: persist `SITE_ADDRESS` in a root-level `.env` so restarts don't need it inline (Compose
auto-loads it for variable substitution).

### 4.6 Point Twilio at the domain (replaces the dev ngrok tunnel)
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
A real domain means you set this **once** — no per-session re-pointing. See
[TWILIO_SETUP.md](TWILIO_SETUP.md) for the full telephony checklist.

---

## 5. Cost controls — keeping the Claude bill down

The Claude API is the main variable cost. The backend ships with three levers (all on by
default, all tunable in `server/.env`); see [`server/.env.example`](server/.env.example) for
the full list.

| Lever | Where | Default | What it does |
|---|---|---|---|
| **Prompt caching** | Anthropic side (`server/llm.py`) | on | Two `cache_control` breakpoints — the large `SHARED_SYSTEM` block (shared across all personas) and the per-persona block — so the stable prefix is billed at ~0.1× on repeat turns. Per-turn retrieved context is appended **after** the breakpoints (uncached, as it must be). |
| **Response cache** | `server/response_cache.py`, wired into `/api/chat` + `/api/chat/stream` | on | A repeat question (same persona / skeptic / industry / history / grounding) is served from cache with **zero** Claude call. A cache hit on the streaming endpoint replays the stored reply as a stream (`X-San-Cached: 1`) so the UX is identical. |
| **Per-IP rate limit** | `server/ratelimit.py`, on `/api/chat*`, `/api/process`, `/api/asr`, `/api/rag/upload` | 60 req / 60 s / IP | Stops one client or bot from running up the bill or saturating the box. Returns `429` + `Retry-After`. X-Forwarded-For-aware (correct behind Caddy / an ALB). Twilio webhooks + static/health are never limited. |

**Single host (default):** both the response cache and the rate-limit counters live
**in-process** (no infra, no dependency). Perfect for one EC2 box. `/api/health` reports the
backend (`"backend":"memory"`) and limits.

**Scaling out → Redis:** the moment you run more than one backend instance, the in-process
cache and counters fragment per-process (low hit rate, per-instance limits). Point the app at
**ElastiCache (Redis)** and both become shared and survive restarts — a **config-only** swap,
no rebuild (the `redis` client is already in `requirements.txt`):
```ini
SAN_REDIS_URL=redis://<elasticache-endpoint>:6379/0
# optional tuning:
SAN_CACHE_TTL=3600        # response-cache entry lifetime (s)
SAN_CACHE_VERSION=1       # bump to bust the whole cache after a KB/prompt change
SAN_RATE_LIMIT=60         # requests per window per IP (0/off disables)
SAN_RATE_WINDOW=60        # window length (s)
```
If `SAN_REDIS_URL` is set but Redis is unreachable, the app logs a warning and falls back to
the in-memory cache — a cache hiccup never takes the request path down.

> **Deferred (env-gated follow-up):** routing simple/short turns to a cheaper model (Haiku)
> while keeping Sonnet/Opus for technical and skeptic turns. Left out of the first pass so the
> reply quality can be A/B'd before committing; it's a `SAN_LLM_MODEL`-style switch when you're
> ready.

---

## 6. Front-end on Amplify (optional — CDN + own domain)

The backend already serves the four front-end files, so for the demo you can **skip Amplify**
entirely (one origin, `SAN_API_BASE` empty). Use Amplify when you want the UI on a CDN /
separate domain.

1. **Connect the repo.** Amplify Console → host the GitHub repo. The build uses
   [`amplify.yml`](amplify.yml), which publishes only `index.html` / `app.js` / `styles.css` /
   `config.js` — never the `server/` source, `.env`, scripts, or docs.
2. **Point it at the backend.** App settings → Environment variables → set
   `SAN_API_BASE = https://sani.example.com` (your EC2 origin). The build bakes it into
   `config.js`; the app reads `window.SAN_API_BASE` at runtime, and the live-mic + Twilio
   WebSockets connect to `wss://<that host>` automatically. CORS is already open
   (`allow_origins=["*"]`), so the Amplify origin reaches the backend.
3. **Custom domain (optional).** Add it in Amplify (it manages the CloudFront cert + CNAME).
4. **Twilio stays pointed at the backend.** `PUBLIC_BASE_URL` and the TwiML App Voice URL must
   be the **backend** origin (not the Amplify URL) — browser calling dials the backend's
   `/api/twilio/*`.

---

## 7. Email (book-a-demo / partner intake) via SES

The `/api/demo/book` and `/api/partner/apply` flows email the lead to `DEMO_NOTIFY_EMAIL` and a
confirmation to the contact. Sending uses plain SMTP and **degrades gracefully** — if SMTP is
unset the lead is still captured and the booking link still shown, just no email goes out. To
send for real on AWS, use **SES via its SMTP interface** (no code change):
```ini
SMTP_HOST=email-smtp.us-east-1.amazonaws.com   # your SES region
SMTP_PORT=587                                  # STARTTLS
SMTP_USER=<SES SMTP username>                  # SES Console → SMTP settings → Create credentials
SMTP_PASS=<SES SMTP password>
SMTP_FROM=sani@your-verified-domain.com        # MUST be a verified SES identity
SMTP_FROM_NAME=Sanas.AI — Sanas
```
Verify the sending domain/identity in SES, create SMTP credentials, and request production
access (the sandbox only sends to verified recipients). Third-party SMTP (Gmail app password,
SendGrid) also works — SES is just the native fit.

---

## 8. Managed-services alternative & scaling out

When one box isn't enough, or you want managed runtime instead of an EC2 you patch:

- **App Runner / ECS Fargate** from [`server/Dockerfile`](server/Dockerfile) — both must run the
  **x86_64** platform (the Dockerfile pins `linux/amd64`; Graviton/arm64 is out). Push the image
  to **ECR** (the Sanas SDK tarball is baked in at build, so it's not a registry pull-through).
  Front with an **ALB** (HTTPS termination via ACM; target group over HTTP to the container;
  WebSocket upgrade is supported). This replaces Caddy.
- **Shared state is the real work, not the runtime.** Before going multi-instance, three
  per-process things must move or be pinned:
  1. **Response cache + rate limiter** → ElastiCache (Redis) via `SAN_REDIS_URL` (§5). Done.
  2. **Live-call dicts** (`STREAMS`/`BRIDGES`/`DEMO`) — a call's media WebSocket and its
     `/api/twilio/toggle` REST call must hit the **same instance**, or the toggle can't find
     the session. Use ALB **sticky sessions**, or move this state to Redis too.
  3. **Admin tokens + lead lists** — in RAM today; back them with Redis/DynamoDB if they must
     survive a redeploy or be shared.
- **RAG store** (`rag_store.json` under `SAN_DATA_DIR=/data`) is a local file. On Fargate, mount
  **EFS** so all tasks share it (or accept that each task has its own copy and re-upload).

> Out of scope for this doc (and this app today): CloudFormation/Terraform IaC, multi-region
> failover, RDS/vector-DB retrieval, and compliance frameworks (FedRAMP/HIPAA/PCI). They're
> reasonable next steps, not requirements for the demo or a single-region production run.

---

## 9. Day-2 operations
| Task | Command |
|---|---|
| Update to latest | `git pull && SITE_ADDRESS=sani.example.com docker compose up -d --build` |
| Logs | `docker compose logs -f san` / `... caddy` |
| Restart | `docker compose restart san` |
| Health (incl. cache + limit) | `curl -s https://sani.example.com/api/health | python3 -m json.tool` |
| **Stop to save money** | `docker compose down` then **Stop** the instance in the EC2 console |
| Resume | **Start** the instance; Compose returns via `restart: unless-stopped` |

## 10. Notes & limits
- **Single instance / in-memory state** — live mic + Twilio bridge sessions, admin logins, the
  response cache, and lead lists don't survive a restart or redeploy. Fine for demos; §8 is the
  path past it.
- **`mode:"unavailable"`** from `/api/health` is the tell that the SDK tarball is missing or
  failed to install (there is no mock — audio endpoints return 503). Re-check `server/vendor/`
  and rebuild.
- **Secrets** stay in `server/.env` (mode 600) on the box for the baseline. For production move
  them to Secrets Manager / SSM (§2) and inject at container start via the instance role.
- **Build is native on AWS** — the EC2/Fargate host is x86-64, so the `linux/amd64` image builds
  fast (unlike emulated on an Apple-Silicon laptop).
