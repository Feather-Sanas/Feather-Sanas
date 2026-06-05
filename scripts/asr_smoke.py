#!/usr/bin/env python3
"""
ASR smoke test — confirm the recognition pipeline works once faster-whisper is
installed and the model has downloaded.

Run (from the repo root, using the SDK venv that has faster-whisper):
    server/.venv310/bin/python scripts/asr_smoke.py [AUDIO.wav] \
        [--reference "the exact words spoken"] [--process]

What it does:
  - transcribes AUDIO with the real ASR and prints transcript + confidence + ms
  - runs a WER self-check (identical=0.0, one substitution=0.25)
  - --reference TEXT : prints the true Word Error Rate vs that reference
  - --process        : also runs AUDIO through the Sanas SDK and prints the
                       before/after recognition delta (and WER, if --reference)

Exits non-zero with install guidance if faster-whisper isn't available.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

# minimal .env load so SAN_ASR_MODEL / SANAS_* are picked up (for --process)
envf = SERVER / ".env"
if envf.exists():
    for line in envf.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import numpy as np  # noqa: E402

DEFAULT_CLIP = Path(
    os.path.expanduser("~/Downloads/sanas_remote_sdk_darwin-arm64_1.0.14 2/examples/test_input.wav")
)


def decode_pcm(path: Path, sr: int = 16000) -> np.ndarray:
    """Decode any audio file to mono s16le PCM at sr via ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed to decode {path}: {proc.stderr.decode()[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.int16).copy()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="?", default=str(DEFAULT_CLIP))
    ap.add_argument("--reference", help="ground-truth transcript for a true WER")
    ap.add_argument("--process", action="store_true",
                    help="also run the clip through the Sanas SDK and compare")
    args = ap.parse_args()

    import asr
    if not asr.available():
        print("✗ faster-whisper is not installed in this interpreter.\n"
              "  Install it:  server/.venv310/bin/pip install -r server/requirements.txt\n"
              "  Then re-run. The model downloads on first use.")
        return 1
    print(f"✓ faster-whisper available · model = {asr.MODEL_NAME}")

    # WER self-check
    a = asr.wer("the quick brown fox", "the quick brown fox")["wer"]
    b = asr.wer("the quick brown fox", "the quick brown dog")["wer"]
    assert a == 0.0 and b == 0.25, (a, b)
    print(f"✓ WER self-check: identical={a}  one-substitution={b}")

    clip = Path(args.audio)
    if not clip.exists():
        sys.exit(f"audio not found: {clip}\nPass a path: asr_smoke.py path/to/clip.wav")
    sr = 16000
    pcm = decode_pcm(clip, sr)
    print(f"\nclip: {clip.name}  ({len(pcm)/sr:.1f}s)")

    before = asr.transcribe(pcm, sr)
    print(f"  before · conf {before['confidence']:>3}  “{before['text']}”")

    if args.reference:
        w = asr.wer(args.reference, before["text"])
        print(f"  WER vs reference: {w['wer']:.3f}  ({w['edits']} edits / {w['ref_words']} words)")

    if args.process:
        import sanas_client
        sanas_client.client.initialize()
        h = sanas_client.client.health()
        print(f"\nSanas SDK: mode={h['mode']} auth={h.get('auth')} model={h['model']}"
              + (f"  ({h['last_error']})" if h.get("last_error") else ""))
        processed = sanas_client.client.process(pcm, sr)
        after = asr.transcribe(processed, sr)
        print(f"  after  · conf {after['confidence']:>3}  “{after['text']}”")
        print(f"  recognition-confidence delta: {after['confidence'] - before['confidence']:+d}")
        if args.reference:
            wb = asr.wer(args.reference, before["text"])["wer"]
            wa = asr.wer(args.reference, after["text"])["wer"]
            print(f"  WER  before {wb:.3f} → after {wa:.3f}  ({(wb-wa):+.3f})")

    print("\n✓ ASR pipeline OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
