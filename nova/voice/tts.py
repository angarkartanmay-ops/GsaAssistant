"""Kokoro-82M (ONNX, CPU) text-to-speech: a warm British female voice blend."""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ..config import MODELS_DIR, VoiceCfg
from .fx import normalize

log = logging.getLogger("nova.tts")

KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def parse_blend(spec: str) -> list[tuple[str, float]]:
    """'bf_emma:0.6,bf_isabella:0.4' -> [('bf_emma', .6), ('bf_isabella', .4)] (weights normalised)."""
    parts = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, w = chunk.partition(":")
        parts.append((name.strip(), float(w) if w else 1.0))
    total = sum(w for _, w in parts) or 1.0
    return [(n, w / total) for n, w in parts]


def split_sentences(text: str, max_len: int = 220) -> list[str]:
    """Sentence chunks so the first one can play while the rest synthesise."""
    sents = re.split(r"(?<=[.!?;:])\s+", text.strip())
    out: list[str] = []
    for s in sents:
        s = s.strip()
        if not s:
            continue
        while len(s) > max_len:
            cut = s.rfind(",", 0, max_len)
            cut = cut if cut > 40 else max_len
            out.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            out.append(s)
    return out


class TTS:
    def __init__(self, cfg: VoiceCfg):
        self.cfg = cfg
        self._kokoro = None
        self._style = None
        self._lock = threading.Lock()
        self.stop_event = threading.Event()
        self.speaking = False

    def model_paths(self) -> tuple[Path, Path]:
        return MODELS_DIR / self.cfg.kokoro_model, MODELS_DIR / self.cfg.kokoro_voices

    def available(self) -> bool:
        m, v = self.model_paths()
        return m.exists() and v.exists()

    def _load(self) -> None:
        if self._kokoro is not None:
            return
        from kokoro_onnx import Kokoro
        m, v = self.model_paths()
        if not (m.exists() and v.exists()):
            raise FileNotFoundError(f"Kokoro model files missing in {MODELS_DIR}. Run `python -m nova setup` "
                                    "or download them from " + KOKORO_BASE)
        self._kokoro = Kokoro(str(m), str(v))
        blend = parse_blend(self.cfg.tts_voice)
        style = None
        for name, w in blend:
            s = self._kokoro.get_voice_style(name) * w
            style = s if style is None else style + s
        self._style = style.astype(np.float32)

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        with self._lock:
            self._load()
            audio, sr = self._kokoro.create(text, voice=self._style, speed=self.cfg.tts_speed,
                                            lang=self.cfg.tts_lang)
        return normalize(audio), sr

    def save(self, text: str, path: Path | str) -> Path:
        import soundfile as sf
        chunks, sr = [], 24000
        for s in split_sentences(text):
            a, sr = self.synth(s)
            chunks += [a, np.zeros(int(sr * 0.12), dtype=np.float32)]
        sf.write(str(path), np.concatenate(chunks) if chunks else np.zeros(1), sr)
        return Path(path)

    def speak(self, text: str, on_level: Optional[Callable[[float], None]] = None,
              device: Optional[str | int] = None) -> bool:
        """Speak blocking, sentence by sentence. Returns False if interrupted."""
        import sounddevice as sd
        self.stop_event.clear()
        self.speaking = True
        sentences = split_sentences(text[: self.cfg.max_spoken_chars])
        try:
            nxt: dict = {}

            def prefetch(i: int) -> None:
                if i < len(sentences):
                    nxt[i] = self.synth(sentences[i])

            prefetch(0)
            for i in range(len(sentences)):
                if self.stop_event.is_set():
                    return False
                th = threading.Thread(target=prefetch, args=(i + 1,), daemon=True)
                th.start()
                audio, sr = nxt.pop(i)
                if not self._play(sd, audio, sr, on_level, device):
                    return False
                th.join()
            return True
        finally:
            self.speaking = False
            if on_level:
                on_level(0.0)

    def _play(self, sd, audio: np.ndarray, sr: int, on_level, device) -> bool:  # noqa: ANN001
        sd.play(audio, sr, device=device)
        start, dur = time.time(), len(audio) / sr
        hop = int(sr * 0.05)
        while time.time() - start < dur:
            if self.stop_event.is_set():
                sd.stop()
                return False
            if on_level:
                i = int((time.time() - start) * sr)
                seg = audio[i:i + hop]
                on_level(float(np.sqrt(np.mean(seg ** 2))) * 3 if seg.size else 0.0)
            time.sleep(0.05)
        sd.wait()
        return True

    def stop(self) -> None:
        self.stop_event.set()

    def play_raw(self, audio: np.ndarray, sr: int, device: Optional[str | int] = None) -> None:
        import sounddevice as sd
        sd.play(audio, sr, device=device)
        sd.wait()
