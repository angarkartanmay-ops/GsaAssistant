"""Speech-to-text with faster-whisper. GPU when it works, CPU int8 when it doesn't."""
from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import MODELS_DIR

log = logging.getLogger("malice.stt")


def add_cuda_dll_dirs() -> None:
    """On Windows, the pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 ship the DLLs
    CTranslate2 needs. Put their bin folders on the DLL search path."""
    if platform.system() != "Windows":
        return
    for base in map(Path, sys.path):
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


class STT:
    def __init__(self, model: str = "small.en", device: str = "auto", prompt: str = ""):
        self.model_name = model
        self.want_device = device
        self.prompt = prompt
        self.model = None
        self.device = "cpu"

    def load(self) -> None:
        if self.model is not None:
            return
        from faster_whisper import WhisperModel
        add_cuda_dll_dirs()
        root = str(MODELS_DIR / "whisper")
        attempts = []
        if self.want_device in ("auto", "cuda"):
            attempts.append(("cuda", "float16"))
        if self.want_device in ("auto", "cpu"):
            attempts.append(("cpu", "int8"))
        last: Optional[Exception] = None
        for device, compute in attempts:
            try:
                m = WhisperModel(self.model_name, device=device, compute_type=compute, download_root=root)
                # A real decode proves the kernels exist for this GPU (RTX 50 needs CUDA 12.8 builds).
                list(m.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])
                self.model, self.device = m, device
                log.info("Whisper %s on %s/%s", self.model_name, device, compute)
                return
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("Whisper on %s failed (%s); trying next option", device, e)
        raise RuntimeError(f"Could not load Whisper model {self.model_name}: {last}")

    def transcribe(self, audio: np.ndarray, hint: str = "") -> str:
        self.load()
        segments, _ = self.model.transcribe(
            audio.astype(np.float32), language="en", beam_size=3, vad_filter=False,
            condition_on_previous_text=False, initial_prompt=(hint or self.prompt) or None)
        return " ".join(s.text.strip() for s in segments).strip()
