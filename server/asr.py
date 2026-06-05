"""
Real ASR for the recognition-comparison panel — faster-whisper (local, offline).

Transcribes before/after audio and reports:
  - the transcript + a recognition-confidence score (from Whisper's avg log-prob)
  - true Word Error Rate when a reference transcript is supplied (the curated
    scenarios pass the clean voice bed as the reference, so WER is genuinely
    computed; uploads have no clean reference, so the panel shows the
    confidence delta instead).

Optional dependency: if faster-whisper isn't installed, available() is False and
the API reports asr_available=false — the rest of the app is unaffected.
"""
from __future__ import annotations

import math
import os
import re
import threading

import numpy as np

try:
    from faster_whisper import WhisperModel
    _OK = True
except Exception:
    WhisperModel = None  # type: ignore
    _OK = False

MODEL_NAME = os.getenv("SAN_ASR_MODEL", "base.en")
_model = None
_lock = threading.Lock()


def available() -> bool:
    return _OK


def _get_model():
    global _model
    if _model is None and _OK:
        with _lock:
            if _model is None:
                _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def transcribe(samples_int16: np.ndarray, sample_rate: int) -> dict | None:
    """Transcribe mono int16 PCM (expects 16 kHz). Returns text + confidence."""
    model = _get_model()
    if model is None:
        return None
    audio = samples_int16.astype(np.float32) / 32768.0
    segments, _info = model.transcribe(audio, language="en", beam_size=1)
    texts, weighted_lp, total_dur, nsp = [], 0.0, 0.0, []
    for s in segments:
        if s.text.strip():
            texts.append(s.text.strip())
        dur = max(0.01, s.end - s.start)
        weighted_lp += s.avg_logprob * dur
        total_dur += dur
        nsp.append(s.no_speech_prob)
    mean_lp = (weighted_lp / total_dur) if total_dur else -5.0
    # avg log-prob -> probability -> 0..100 "recognition confidence"
    confidence = round(max(0.0, min(100.0, 100.0 * math.exp(mean_lp))))
    return {
        "text": " ".join(texts).strip(),
        "avg_logprob": round(mean_lp, 3),
        "no_speech_prob": round(sum(nsp) / len(nsp), 3) if nsp else 1.0,
        "confidence": confidence,
    }


def _normalize(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", s.lower()).split()


def wer(reference: str, hypothesis: str) -> dict:
    """Standard word-error-rate via word-level Levenshtein distance."""
    ref, hyp = _normalize(reference), _normalize(hypothesis)
    if not ref:
        return {"wer": None, "ref_words": 0}
    # DP edit distance
    prev = list(range(len(hyp) + 1))
    for i, rw in enumerate(ref, 1):
        cur = [i]
        for j, hw in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return {"wer": round(prev[-1] / len(ref), 3), "ref_words": len(ref), "edits": prev[-1]}
