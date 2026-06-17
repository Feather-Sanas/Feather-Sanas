#!/usr/bin/env bash
# Bring the public tunnel up on the SAME reserved ngrok domain every time, so
# PUBLIC_BASE_URL (server/.env) and the Twilio TwiML App Voice URL never need
# re-pointing. Run this instead of a bare `ngrok http 8000`.
#
#   ./scripts/tunnel.sh            # uses the pinned domain below
#   SANI_TUNNEL_DOMAIN=foo.ngrok-free.dev ./scripts/tunnel.sh   # override
#
# Requires ngrok 3.5+ ( `--url` flag ). The domain must be reserved to your
# ngrok account (free tier includes one static domain).
set -euo pipefail

DOMAIN="${SANI_TUNNEL_DOMAIN:-overcast-acronym-traction.ngrok-free.dev}"
PORT="${SANI_PORT:-8000}"

echo "Pinning public tunnel:  https://${DOMAIN}  →  http://localhost:${PORT}"
echo "(PUBLIC_BASE_URL + the Twilio TwiML App Voice URL should both use this domain.)"
exec ngrok http "${PORT}" --url="https://${DOMAIN}" --log=/tmp/ngrok.log
