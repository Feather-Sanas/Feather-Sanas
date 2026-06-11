"""
Thin wrapper around the Sanas Remote SDK (`sanas_remote_sdk`).

The ONE place that talks to the native SDK. Verified against the SDK's own
examples/basic_usage.py + wav_utils.py (v1.0.14):
  - auth: InitParams.apiKey (preferred; takes precedence) OR accountId+accountSecret
  - ProcessSamples takes a Python list of floats in [-1.0, 1.0] (mono) and returns
    the same; audio is fed in fixed chunks (20ms) with the last chunk zero-padded
  - secureMedia defaults False (matches the working demo)

Falls back to a clearly-labelled MOCK when the SDK isn't installed, so the
front-end stays functional during development.

Docs: https://developer.sanas.ai/Docs/Getting-Started/Quick-Start
"""
from __future__ import annotations

import os
import threading
import time
import numpy as np

# Model -> required sample rate, per the Quick Start model table.
MODEL_SAMPLE_RATES = {
    "SE2.2": 16000,            # Speech Enhancement, ultra-fidelity
    "SE2.1": 16000,            # Speech Enhancement, standard
    "VI_G_NC3.0": 16000,       # Noise cancellation (the SDK example default)
    "AGENTIC_VI_G_NC": 16000,
    "AGENTIC_ST_NC": 16000,
    "AGENTIC_VI_GT_NC": 8000,
}
DEFAULT_MODEL = os.getenv("SANAS_MODEL", "SE2.2")

# SDK streams fixed-size frames in real time; the example uses 20ms.
FRAME_MS = int(os.getenv("SANAS_FRAME_MS", "20"))
# Silent frames fed after the input to flush the pipeline's latency tail.
DRAIN_MS = int(os.getenv("SANAS_DRAIN_MS", "800"))
SECURE_MEDIA = os.getenv("SANAS_SECURE_MEDIA", "false").lower() in ("1", "true", "yes")
READY_TIMEOUT = float(os.getenv("SANAS_READY_TIMEOUT", "10"))

try:
    import sanas_remote_sdk  # type: ignore
    _SDK_AVAILABLE = True
except Exception:
    sanas_remote_sdk = None  # type: ignore
    _SDK_AVAILABLE = False


class SanasClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sdk = None
        self._initialized = False
        self.mode = "mock"          # "real" once the SDK initializes
        self.auth = None            # "api_key" | "account" once initialized
        self.last_error: str | None = None
        self.model = DEFAULT_MODEL
        self.sample_rate = MODEL_SAMPLE_RATES.get(self.model, 16000)

    # ---- lifecycle -------------------------------------------------------
    def initialize(self) -> None:
        endpoint = os.getenv("SANAS_ENDPOINT")
        api_key = os.getenv("SANAS_API_KEY")
        account_id = os.getenv("SANAS_ACCOUNT_ID")
        account_secret = os.getenv("SANAS_ACCOUNT_SECRET")

        if not _SDK_AVAILABLE:
            self.last_error = "sanas_remote_sdk not installed (mock mode)"
            return
        if not endpoint:
            self.last_error = "SANAS_ENDPOINT not set (mock mode)"
            return
        if not (api_key or (account_id and account_secret)):
            self.last_error = "no SANAS_API_KEY or account credentials set (mock mode)"
            return

        try:
            sdk = sanas_remote_sdk.CreateRemoteSDK()
            params = sanas_remote_sdk.InitParams()
            params.secureMedia = SECURE_MEDIA
            params.remoteEndpoint = endpoint
            if api_key:                       # apiKey takes precedence (per SDK examples)
                params.apiKey = api_key
                self.auth = "api_key"
            else:
                params.accountId = account_id
                params.accountSecret = account_secret
                self.auth = "account"
            result = sdk.Initialize(params)
            if result != sanas_remote_sdk.InitSDKResult.SUCCESS:
                self.last_error = f"Initialize returned {result}"
                self.auth = None
                return
            self._sdk = sdk
            self._initialized = True
            self.mode = "real"
            self.last_error = None
        except Exception as exc:  # keep the service up, fall back to mock
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.auth = None

    def shutdown(self) -> None:
        if self._sdk is not None and self._initialized:
            try:
                self._sdk.Shutdown()
            finally:
                self._initialized = False

    # ---- status ----------------------------------------------------------
    def health(self) -> dict:
        active = 0
        if self.mode == "real" and self._sdk is not None:
            try:
                active = self._sdk.GetActiveProcessorCount()
            except Exception:
                active = 0
        return {
            "mode": self.mode,
            "auth": self.auth,
            "sdk_available": _SDK_AVAILABLE,
            "initialized": self._initialized,
            "secure_media": SECURE_MEDIA,
            "model": self.model,
            "sample_rate": self.sample_rate,
            "frame_ms": FRAME_MS,
            "active_processors": active,
            "last_error": self.last_error,
        }

    # ---- processing ------------------------------------------------------
    def process(self, samples: np.ndarray, sample_rate: int, model: str | None = None) -> np.ndarray:
        """Process mono int16 PCM through the chosen model; return mono int16 PCM."""
        model = model or self.model
        if self.mode == "real" and self._initialized:
            return self._process_real(samples, sample_rate, model)
        return self._process_mock(samples, sample_rate)

    def _process_real(self, samples: np.ndarray, sample_rate: int, model: str) -> np.ndarray:
        assert sanas_remote_sdk is not None
        floats = (samples.astype(np.float32) / 32768.0).tolist()  # SDK wants [-1, 1] floats
        chunk = max(1, int(sample_rate * FRAME_MS / 1000))

        ready = threading.Event()
        failed = threading.Event()

        def state_callback(state, reason):
            if state == sanas_remote_sdk.ProcessorState.READY:
                ready.set()
            elif state in (sanas_remote_sdk.ProcessorState.FAILED,
                           sanas_remote_sdk.ProcessorState.DISCONNECTED):
                failed.set()

        with self._lock:
            audio_params = sanas_remote_sdk.AudioParams()
            audio_params.modelName = model
            audio_params.sampleRate = sample_rate
            processor, create_result = self._sdk.CreateAudioProcessor(audio_params, state_callback)
            if create_result != sanas_remote_sdk.CreateProcessorResult.SUCCESS:
                raise RuntimeError(f"CreateAudioProcessor failed: {create_result}")
            try:
                if not ready.wait(timeout=READY_TIMEOUT):
                    raise RuntimeError("processor failed" if failed.is_set()
                                       else "processor READY timeout")
                # This is a live real-time engine: it emits processed audio at
                # real-time rate with a fixed pipeline latency, so frames MUST be
                # fed on a ~FRAME_MS cadence (flooding it returns silence). After
                # the input ends we feed silent "drain" frames to pull the tail
                # still in the pipeline back out. Wall-clock ~= clip duration.
                frame_dur = FRAME_MS / 1000.0
                silent = [0.0] * chunk
                drain = int(round(DRAIN_MS / FRAME_MS))
                n_in = (len(floats) + chunk - 1) // chunk

                out: list[float] = []
                t0 = time.monotonic()
                for idx in range(n_in + drain):
                    target = t0 + idx * frame_dur
                    delay = target - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    if idx < n_in:
                        frame = floats[idx * chunk:(idx + 1) * chunk]
                        if len(frame) < chunk:
                            frame = frame + [0.0] * (chunk - len(frame))
                    else:
                        frame = silent
                    out.extend(processor.ProcessSamples(frame))

                arr = np.clip(np.asarray(out, dtype=np.float32), -1.0, 1.0)
                return (arr * 32767.0).astype(np.int16)
            finally:
                self._sdk.DestroyAudioProcessor(processor)

    @staticmethod
    def _process_mock(samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """Deterministic stand-in (high-pass + soft noise gate) so the UX works
        without the native SDK. NOT the Sanas model — reported as mock by /api/health."""
        x = samples.astype(np.float32) / 32768.0
        hp = np.empty_like(x)
        a, prev_x, prev_y = 0.97, 0.0, 0.0
        for i in range(len(x)):
            y = a * (prev_y + x[i] - prev_x)
            hp[i] = y
            prev_x, prev_y = x[i], y
        win = max(1, sample_rate // 100)
        env = np.convolve(np.abs(hp), np.ones(win) / win, mode="same")
        gate = np.clip((env - 0.012) / 0.05, 0.0, 1.0)
        out = np.clip(hp * (0.6 + 0.4 * gate) * 1.1, -1.0, 1.0)
        return (out * 32767.0).astype(np.int16)


class StreamSession:
    """A persistent AudioProcessor for the live-mic path. Unlike batch process(),
    the processor stays open across frames; the client feeds mic frames (exactly
    `frame_samples` each) as they arrive and plays back what comes out."""

    def __init__(self, sdk, model: str, sample_rate: int) -> None:
        self._sdk = sdk
        self.model = model
        self.sample_rate = sample_rate
        self.frame_samples = max(1, int(sample_rate * FRAME_MS / 1000))
        self._lock = threading.Lock()
        ready = threading.Event()
        failed = threading.Event()

        def cb(state, reason):
            if state == sanas_remote_sdk.ProcessorState.READY:
                ready.set()
            elif state in (sanas_remote_sdk.ProcessorState.FAILED,
                           sanas_remote_sdk.ProcessorState.DISCONNECTED):
                failed.set()

        ap = sanas_remote_sdk.AudioParams()
        ap.modelName = model
        ap.sampleRate = sample_rate
        self._proc, res = sdk.CreateAudioProcessor(ap, cb)
        if res != sanas_remote_sdk.CreateProcessorResult.SUCCESS:
            raise RuntimeError(f"CreateAudioProcessor failed: {res}")
        if not ready.wait(timeout=READY_TIMEOUT):
            try: sdk.DestroyAudioProcessor(self._proc)
            except Exception: pass
            raise RuntimeError("processor failed" if failed.is_set() else "processor READY timeout")

    def process(self, frame_floats):
        """Process one frame (list[float] of length frame_samples) -> list[float]."""
        with self._lock:
            return self._proc.ProcessSamples(frame_floats)

    def close(self) -> None:
        try: self._sdk.DestroyAudioProcessor(self._proc)
        except Exception: pass


def _create_stream(self, model=None, sample_rate=None):
    """Open a live streaming session, or None if not in real mode. Retries a few
    times: a just-ended call (e.g. a prior /api/process) tears its SIP session
    down asynchronously, so CreateAudioProcessor can transiently fail with a
    busy/limit code until the slot frees."""
    if self.mode != "real" or not self._initialized:
        return None
    model = model or self.model
    sr = sample_rate or MODEL_SAMPLE_RATES.get(model, 16000)
    last = None
    for attempt in range(4):
        try:
            return StreamSession(self._sdk, model, sr)
        except Exception as exc:
            last = exc
            time.sleep(1.5)
    raise last


SanasClient.create_stream = _create_stream


# module-level singleton
client = SanasClient()
