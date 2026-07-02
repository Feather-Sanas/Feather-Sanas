# Sani on AWS — Terraform

Infrastructure-as-code for the split deploy in [`../../DEPLOY_AWS.md`](../../DEPLOY_AWS.md):

- **Front-end → Amplify Hosting** (builds from the repo's `amplify.yml`, points at the backend via `SAN_API_BASE`).
- **Backend → one x86-64 EC2** behind **Caddy** (auto-HTTPS), running the app via `docker-compose`.
- Supporting: **Secrets Manager** (the backend `server/.env`), **S3** (the Sanas Linux SDK tarball), **Route 53** (API A record + SES DNS), **SES** (book-a-demo email), least-privilege **IAM** + **SSM Session Manager**.

Amplify cannot run the backend — it's serverless, and the backend needs a long-running process for the native Sanas SDK's SIP/RTP, the WebSockets (live mic + Twilio media), and in-memory call state. Hence the split.

## What you must supply

| Thing | Why |
|---|---|
| A **Route 53 hosted zone** for your domain (in this account) | HTTPS is mandatory — the Amplify (HTTPS) UI can't call a plain-HTTP backend, and Twilio/mic need it. |
| The **Sanas Linux x86-64 SDK tarball** | Installed at image-build time; without it the backend runs in **mock mode**. |
| The backend **`server/.env`** values | Anthropic key, Twilio creds, `RAG_ADMIN_PASSWORD`, `PUBLIC_BASE_URL`, Sanas creds (SMTP comes from Terraform outputs). |
| A **GitHub PAT** (`repo` + `admin:repo_hook`) | So Amplify can connect the repo. Skip with `enable_amplify = false`. |
| **AWS credentials** for `terraform` | Provisioning rights (EC2/VPC/EIP, Route 53, S3, Secrets Manager, IAM, Amplify, SES). |

## Order of operations

Because the instance pulls the `.env` and the SDK on boot, create the *containers* first, populate them, then bring up the rest.

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars   # then edit
terraform init

# 1) create just the secret + the SDK bucket (with its hardening: block public
#    access, ownership, encryption — so the uploaded tarball is never exposed)
terraform apply \
  -target=aws_secretsmanager_secret.env \
  -target=aws_s3_bucket.sdk \
  -target=aws_s3_bucket_public_access_block.sdk \
  -target=aws_s3_bucket_ownership_controls.sdk \
  -target=aws_s3_bucket_server_side_encryption_configuration.sdk

# 2) upload the SDK tarball (name must match var.sdk_object_key)
terraform output -raw sdk_bucket   # e.g. sani-sdk-1234567890-us-east-1
aws s3 cp /path/to/sanas_remote_sdk_linux_x86-64_<ver>.tar.gz \
  "s3://$(terraform output -raw sdk_bucket)/sanas_remote_sdk_linux_x86-64.tar.gz"

# 3) populate the .env secret (plain dotenv text — see "The .env secret" below)
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw env_secret_name)" \
  --secret-string file://server.env.filled

# 4) provision everything else (EC2 boots, pulls the secret + tarball, builds, runs)
terraform apply
```

If you populate the secret / upload the tarball *after* the box is already up, re-run the bootstrap on the instance:

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)"
sudo bash /opt/sani/infra/aws/bootstrap-rerun.sh
```

## The `.env` secret

The secret's value is the **entire `server/.env` file as plain text** (the instance writes it verbatim to `server/.env`). Start from [`../../server/.env.example`](../../server/.env.example). The values Terraform generates:

```ini
PUBLIC_BASE_URL=https://api.your-domain.com     # = `terraform output backend_url`
ANTHROPIC_API_KEY=          # paste your Anthropic API key
RAG_ADMIN_PASSWORD=...
# Twilio (calling)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
# ...the rest of the Twilio + Sanas keys from server/.env.example...
# Email via SES (from terraform outputs):
SMTP_HOST=email-smtp.us-east-1.amazonaws.com     # = `terraform output ses_smtp_host`
SMTP_PORT=587
SMTP_USER=...                                     # = `terraform output ses_smtp_user`
SMTP_PASS=...                                     # = `terraform output -raw ses_smtp_password`
SMTP_FROM=demos@your-domain.com                   # a verified SES sender
```

Cost controls (`SAN_CACHE`, `SAN_RATE_LIMIT`, …) default sensibly — override in the secret only if needed. To move the response cache to a shared store later, add `SAN_REDIS_URL` (e.g. an ElastiCache endpoint); the app swaps to Redis with no code change.

## After apply

1. **Point Twilio at the backend** — set the number's Voice URL and the TwiML App Voice URL to `https://api.your-domain.com/api/twilio/voice` (see [`../../TWILIO_SETUP.md`](../../TWILIO_SETUP.md) / `DEPLOY_AWS.md` §6). A real domain means you do this once.
2. **SES sandbox** — a new SES account only sends to verified addresses (`notify_email` is verified for you). To email real demo contacts, request **SES production access** in the console.
3. **Verify:**
   ```bash
   curl -s "$(terraform output -raw backend_url)/api/health" | python3 -m json.tool
   # expect mode:"real", sdk_available:true, llm_available:true; also shows cache + rate_limit
   ```
   Open `terraform output -raw amplify_branch_url` for the UI.

## Cost & teardown

Roughly **~$21/mo** (t3.small 24/7 + EBS + EIP + Route 53) plus Amplify/SES usage — see `DEPLOY_AWS.md`. Stop the instance when idle to pay only EBS + EIP.

```bash
terraform destroy   # force_destroy on the S3 bucket removes the tarball too
```

> **State holds secrets** (SES SMTP password, ARNs). For anything beyond a demo, enable the encrypted S3 backend in `versions.tf`.
