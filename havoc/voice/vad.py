"""Streaming voice-activity detection: Silero v6 (bundled with faster-whisper) or energy fallback."""
from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger("havoc.vad")
FRAME = 512  # 32 ms at 16 kHz
CONTEXT = 64


class SileroStream:
    def __init__(self) -> None:
        import onnxruntime as ort
        from faster_whisper.utils import get_assets_path
        path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.ctx = np.zeros(CONTEXT, dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.ctx, frame.astype(np.float32)])[None, :]
        prob, self.h, self.c = self.sess.run(None, {"input": x, "h": self.h, "c": self.c})
        self.ctx = frame[-CONTEXT:].astype(np.float32)
        return float(np.asarray(prob).reshape(-1)[0])


class EnergyVAD:
    """Adaptive-threshold RMS detector, used only when Silero can't load."""

    def __init__(self) -> None:
        self.noise = 0.01

    def reset(self) -> None:
        pass

    def __call__(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame ** 2)))
        self.noise = 0.995 * self.noise + 0.005 * min(rms, self.noise * 3)
        return float(np.clip((rms / max(self.noise, 1e-4) - 2.0) / 4.0, 0, 1))


def make_vad():  # noqa: ANN201
    try:
        return SileroStream()
    except Exception as e:  # noqa: BLE001
        log.warning("Silero VAD unavailable (%s); using energy VAD", e)
        return EnergyVAD()


class Segmenter:
    """Feeds 512-sample frames, emits complete utterances (np.float32 @16 kHz)."""

    def __init__(self, vad, threshold: float = 0.5, silence_ms: int = 750,  # noqa: ANN001
                 min_speech_ms: int = 250, max_s: float = 20.0, preroll_ms: int = 320):
        self.vad = vad
        self.th = threshold
        self.silence_frames = int(silence_ms / 32)
        self.min_frames = int(min_speech_ms / 32)
        self.max_frames = int(max_s * 1000 / 32)
        self.preroll = int(preroll_ms / 32)
        self.reset()

    def reset(self) -> None:
        self.buf: list[np.ndarray] = []
        self.pre: list[np.ndarray] = []
        self.active = False
        self.speech_frames = 0
        self.quiet = 0
        self.vad.reset()

    def feed(self, frame: np.ndarray) -> np.ndarray | None:
        p = self.vad(frame)
        if not self.active:
            self.pre = (self.pre + [frame])[-self.preroll:]
            if p >= self.th:
                self.active = True
                self.buf = list(self.pre)
                self.speech_frames = 1
                self.quiet = 0
            return None
        self.buf.append(frame)
        if p >= self.th - 0.15:
            self.speech_frames += 1
            self.quiet = 0
        else:
            self.quiet += 1
        if self.quiet >= self.silence_frames or len(self.buf) >= self.max_frames:
            audio = np.concatenate(self.buf)
            enough = self.speech_frames >= self.min_frames
            self.active, self.buf, self.pre, self.speech_frames, self.quiet = False, [], [], 0, 0
            return audio if enough else None
        return None
