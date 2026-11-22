"""The 'menace' effects chain that turns a clean Kokoro voice into something Ultron-adjacent.

Ultron in the film is a human performance (calm, sardonic) pushed through sound design. We
copy the recipe, not the actor:
  * pitch down a touch for weight
  * a quiet octave-down double, the "there is something big behind this voice" layer
  * a faint ring-mod shimmer and chorus doubling for the synthetic edge
  * low-shelf warmth, gentle compression, a small metallic room
`menace` 0 bypasses everything; 3 is full effect.
"""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("malice.fx")


def _ring_mod(x: np.ndarray, sr: int, freq: float, depth: float) -> np.ndarray:
    if depth <= 0:
        return x
    t = np.arange(len(x), dtype=np.float32) / sr
    carrier = (1.0 - depth) + depth * np.sin(2 * np.pi * freq * t).astype(np.float32)
    return x * carrier


def _normalize(x: np.ndarray, peak: float = 0.89) -> np.ndarray:
    m = float(np.max(np.abs(x))) if x.size else 0.0
    return x if m < 1e-6 else (x / m * peak).astype(np.float32)


def menace_fx(audio: np.ndarray, sr: int, menace: float = 2.0) -> np.ndarray:
    m = float(np.clip(menace / 3.0, 0.0, 1.0))
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if m == 0 or x.size == 0:
        return x
    try:
        from pedalboard import (Chorus, Compressor, Gain, HighpassFilter, HighShelfFilter, Limiter,
                                LowShelfFilter, Pedalboard, PitchShift, Reverb)
    except ImportError:
        log.warning("pedalboard missing; using the light numpy chain")
        return _normalize(_ring_mod(x, sr, 48.0, 0.10 * m))

    main = Pedalboard([PitchShift(semitones=-1.6 * m)])(x, sr)
    sub = Pedalboard([PitchShift(semitones=-12.0), HighShelfFilter(cutoff_frequency_hz=1800, gain_db=-14)])(x, sr)
    n = min(len(main.reshape(-1)), len(sub.reshape(-1)))
    mix = main.reshape(-1)[:n] + sub.reshape(-1)[:n] * (0.16 * m)
    mix = _ring_mod(mix, sr, 46.0, 0.07 * m)
    board = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=70),
        LowShelfFilter(cutoff_frequency_hz=180, gain_db=3.5 * m),
        HighShelfFilter(cutoff_frequency_hz=7000, gain_db=-2.0 * m),
        Chorus(rate_hz=0.45, depth=0.18, centre_delay_ms=8.0, feedback=0.05, mix=0.22 * m),
        Compressor(threshold_db=-20, ratio=3.0, attack_ms=5, release_ms=120),
        Reverb(room_size=0.16, damping=0.75, wet_level=0.09 * m, dry_level=0.95, width=0.5),
        Gain(gain_db=2.0),
        Limiter(threshold_db=-1.0),
    ])
    out = board(mix.astype(np.float32), sr).reshape(-1)
    return _normalize(out)


def chime(sr: int = 24000, wake: bool = True) -> np.ndarray:
    """Two low tones: rising when it wakes, falling when it goes back to sleep."""
    freqs = (196.0, 293.7) if wake else (293.7, 196.0)
    parts = []
    for f in freqs:
        t = np.arange(int(sr * 0.11)) / sr
        env = np.minimum(1, t * 60) * np.exp(-t * 14)
        tone = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2 * t) + 0.15 * np.sin(2 * np.pi * f * 0.5 * t)
        parts.append((tone * env * 0.35).astype(np.float32))
    return np.concatenate(parts)
