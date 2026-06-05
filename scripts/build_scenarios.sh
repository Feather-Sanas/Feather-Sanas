#!/usr/bin/env bash
# Build the curated Audio Showroom before/after pairs.
#
# For each scenario it produces two files the front-end plays directly:
#   assets/<key>_before.wav   — the raw clip (16kHz mono)
#   assets/<key>_after.wav    — the same clip processed by the Sanas SDK backend
#
# "before" source, in priority order:
#   1. assets/raw/<key>.wav   — a REAL recording you dropped in (preferred)
#   2. otherwise a synthetic placeholder generated with ffmpeg
#
# "after" is always produced by POSTing the before clip to the running backend
# (/api/process). Point at your real-SDK backend to get true Sanas output:
#   SAN_API=http://localhost:8000 ./scripts/build_scenarios.sh    # docker (real SDK)
#   SAN_API=http://localhost:8078 ./scripts/build_scenarios.sh    # local mock
#
# Requires: ffmpeg, curl, and the backend running.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="$ROOT/assets"
RAW="$ASSETS/raw"
SAN_API="${SAN_API:-http://localhost:8078}"
MODEL="${SANAS_MODEL:-SE2.2}"
mkdir -p "$ASSETS" "$RAW"

# Build a placeholder "before" by mixing the shared real-voice bed
# (assets/raw/_voice.wav) with scenario-appropriate noise. Real speech is required
# for a meaningful demo — Speech Enhancement removes non-speech entirely, so a pure
# tone would come back silent. Replace assets/raw/<key>.wav with your own recording
# to use real, scenario-specific audio.
VOICE="$RAW/_voice.wav"
gen_placeholder() {
  local key="$1" out="$2"
  if [ ! -f "$VOICE" ]; then
    echo "  [warn] no voice bed at assets/raw/_voice.wav — output will be non-speech and may come back silent" >&2
    ffmpeg -y -hide_banner -loglevel error -f lavfi -i "sine=frequency=180:duration=6" -ar 16000 -ac 1 "$out"
    return
  fi
  local dur; dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VOICE")
  case "$key" in
    cafe)     # broadband background noise (espresso machines, chatter)
      ffmpeg -y -hide_banner -loglevel error -i "$VOICE" \
        -f lavfi -t "$dur" -i "anoisesrc=color=white:amplitude=0.06" \
        -filter_complex "[0:a]volume=1.0[v];[v][1:a]amix=inputs=2:duration=first:weights=1 0.7" \
        -ar 16000 -ac 1 "$out" ;;
    floor)    # overlapping call-center "babble" — band-limited noise
      ffmpeg -y -hide_banner -loglevel error -i "$VOICE" \
        -f lavfi -t "$dur" -i "anoisesrc=color=pink:amplitude=0.10" \
        -filter_complex "[1:a]bandpass=f=1200:width_type=h:w=900[b];[0:a][b]amix=inputs=2:duration=first:weights=1 0.8" \
        -ar 16000 -ac 1 "$out" ;;
    offshore) # lighter room noise — dialect baseline
      ffmpeg -y -hide_banner -loglevel error -i "$VOICE" \
        -f lavfi -t "$dur" -i "anoisesrc=color=brown:amplitude=0.04" \
        -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.5" \
        -ar 16000 -ac 1 "$out" ;;
    *) echo "unknown scenario: $key" >&2; return 1 ;;
  esac
}

echo "Backend: $SAN_API   Model: $MODEL"
curl -sf "$SAN_API/api/health" >/dev/null || { echo "Backend not reachable at $SAN_API — start it first." >&2; exit 1; }

for key in cafe floor offshore; do
  before="$ASSETS/${key}_before.wav"
  after="$ASSETS/${key}_after.wav"
  if [ -f "$RAW/$key.wav" ]; then
    echo "[$key] using real recording assets/raw/$key.wav"
    ffmpeg -y -hide_banner -loglevel error -i "$RAW/$key.wav" -ar 16000 -ac 1 "$before"
  else
    echo "[$key] no raw recording — generating synthetic placeholder (replace assets/raw/$key.wav with a real clip)"
    gen_placeholder "$key" "$before"
  fi
  echo "[$key] processing through Sanas backend -> $(basename "$after")"
  curl -sf -F "file=@$before" "$SAN_API/api/process?model=$MODEL" -o "$after"
done

echo "Done. ${ASSETS}/<scenario>_{before,after}.wav written."
echo "Mode used (real vs mock) is whatever the backend reported at /api/health."
