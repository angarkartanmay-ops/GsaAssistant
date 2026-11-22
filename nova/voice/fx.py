"""Small audio helpers: loudness normalising and the wake/sleep chime. The voice itself is clean."""
from __future__ import annotations

import numpy as np


def normalize(x: np.ndarray, peak: float = 0.89) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    m = float(np.max(np.abs(x))) if x.size else 0.0
    return x if m < 1e-6 else (x / m * peak).astype(np.float32)


def chime(sr: int = 24000, wake: bool = True) -> np.ndarray:
    """Two soft bright tones: rising when it starts listening, falling when it stops."""
    freqs = (880.0, 1174.7) if wake else (1174.7, 880.0)
    parts = []
    for f in freqs:
        t = np.arange(int(sr * 0.09)) / sr
        env = np.minimum(1, t * 80) * np.exp(-t * 22)
        tone = np.sin(2 * np.pi * f * t) + 0.2 * np.sin(2 * np.pi * f * 2 * t)
        parts.append((tone * env * 0.25).astype(np.float32))
    return np.concatenate(parts)
