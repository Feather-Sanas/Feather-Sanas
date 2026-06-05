#!/usr/bin/env bash
# Run the San backend natively on macOS (Apple Silicon) with the REAL Sanas SDK.
#
# The darwin-arm64 wheel runs natively — no Docker needed on a Mac. This script
# creates a Python 3.10 venv, installs the SDK wheel + backend deps, and starts
# the server. Credentials are read from server/.env automatically.
#
# Usage:
#   ./scripts/run_mac.sh [/path/to/sanas_remote_sdk-*.whl | /path/to/sdk_folder]
# If no path is given it looks in server/vendor/*.whl.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="$ROOT/server"
PORT="${PORT:-8080}"

# locate the wheel
WHEEL="${1:-}"
if [ -n "$WHEEL" ] && [ -d "$WHEEL" ]; then
  WHEEL="$(ls -1 "$WHEEL"/sanas_remote_sdk-*.whl 2>/dev/null | head -n1 || true)"
fi
[ -z "$WHEEL" ] && WHEEL="$(ls -1 "$SERVER"/vendor/sanas_remote_sdk-*.whl 2>/dev/null | head -n1 || true)"

command -v python3.10 >/dev/null || { echo "python3.10 not found. Install: brew install python@3.10" >&2; exit 1; }

if [ ! -d "$SERVER/.venv310" ]; then
  echo "[setup] creating Python 3.10 venv..."
  python3.10 -m venv "$SERVER/.venv310"
  "$SERVER/.venv310/bin/pip" install -q --upgrade pip
  "$SERVER/.venv310/bin/pip" install -q -r "$SERVER/requirements.txt"
fi

if ! "$SERVER/.venv310/bin/python" -c "import sanas_remote_sdk" 2>/dev/null; then
  [ -z "$WHEEL" ] && { echo "Sanas SDK wheel not found. Pass its path or drop it in server/vendor/." >&2; exit 1; }
  echo "[setup] installing Sanas SDK: $(basename "$WHEEL")"
  "$SERVER/.venv310/bin/pip" install -q "$WHEEL"
fi

echo "[run] starting backend on http://localhost:$PORT  (creds from server/.env)"
exec "$SERVER/.venv310/bin/uvicorn" main:app --app-dir "$SERVER" --port "$PORT"
