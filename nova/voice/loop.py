"""Mic -> VAD -> (wake word) -> Whisper -> agent -> Kokoro, in a background thread.

States: idle (waiting for "Nova"), listening (next utterance is a command), speaking.
Half-duplex: the mic is ignored while it talks, so it never hears itself. Press the
push-to-talk hotkey (or the HUD mic button) to cut it off and talk.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import Any, Optional

import numpy as np

from ..brain.antislop import for_speech
from .fx import chime
from .stt import STT
from .tts import TTS
from .vad import FRAME, Segmenter, make_vad
from .wake import match_wake

log = logging.getLogger("nova.voice")
SR = 16000


class VoiceLoop:
    def __init__(self, rt: Any, loop: asyncio.AbstractEventLoop):
        self.rt = rt
        self.cfg = rt.cfg.voice
        self.loop = loop
        self.tts = TTS(self.cfg)
        names = rt.cfg.assistant.wake_words + [rt.cfg.assistant.spoken_name]
        self.stt = STT(self.cfg.stt_model, self.cfg.stt_device,
                       prompt=f"{rt.cfg.assistant.spoken_name}, GSA, Gemini, Discord, WhatsApp, dashboard.")
        self.wake_stt = STT(self.cfg.wake_model, "cpu", prompt=", ".join(names))
        self.frames: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=400)
        self.state = "idle"
        self.awake_until = 0.0
        self.running = False
        self.muted = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._last_level_t = 0.0

    # ---------- lifecycle ----------
    def start(self) -> None:
        import sounddevice as sd
        self.stt.load()
        if self.cfg.wake_enabled:
            try:
                self.wake_stt.load()
            except Exception as e:  # noqa: BLE001
                log.warning("wake model failed (%s); wake word uses the main model", e)
                self.wake_stt = self.stt
        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=FRAME,
                                      device=self.cfg.input_device, callback=self._on_audio)
        self._stream.start()
        self.running = True
        self._thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self._thread.start()
        self._register_hotkey()
        log.info("Voice loop running (wake: %s, hotkey: %s)", self.cfg.wake_enabled, self.cfg.push_to_talk_hotkey)

    def stop(self) -> None:
        self.running = False
        self.tts.stop()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def _register_hotkey(self) -> None:
        try:
            import keyboard  # type: ignore[import-not-found]
            keyboard.add_hotkey(self.cfg.push_to_talk_hotkey, self.trigger)
        except Exception as e:  # noqa: BLE001 - not on Windows / no permission
            log.info("Global hotkey unavailable (%s); use the HUD mic button", e)

    # ---------- inputs ----------
    def _on_audio(self, indata, frames, t, status) -> None:  # noqa: ANN001
        frame = indata[:, 0].copy()
        lvl = float(np.sqrt(np.mean(frame ** 2)))
        now = time.time()
        if now - self._last_level_t > 0.08 and self.state != "speaking":  # ~12 updates/s for the HUD
            self._last_level_t = now
            self._emit({"type": "level", "source": "mic", "value": min(1.0, lvl * 12)})
        try:
            self.frames.put_nowait(frame)
        except queue.Full:
            pass

    def trigger(self) -> None:
        """Hotkey / mic button: interrupt speech and listen for a command."""
        if self.tts.speaking:
            self.tts.stop()
        self._wake(play=True)

    def _wake(self, play: bool) -> None:
        self.awake_until = time.time() + self.cfg.follow_up_seconds + 3
        self._set_state("listening")
        if play:
            threading.Thread(target=self.tts.play_raw, args=(chime(24000, True), 24000, self.cfg.output_device),
                             daemon=True).start()

    # ---------- main loop ----------
    def _run(self) -> None:
        seg = Segmenter(make_vad(), self.cfg.vad_threshold, self.cfg.silence_ms)
        while self.running:
            try:
                frame = self.frames.get(timeout=0.5)
            except queue.Empty:
                self._check_timeout()
                continue
            if self.muted or self.tts.speaking:
                seg.reset()
                continue
            utt = seg.feed(frame)
            self._check_timeout()
            if utt is not None:
                try:
                    self._handle_utterance(utt)
                except Exception:  # noqa: BLE001
                    log.exception("voice turn failed")
                    self._set_state("idle")
                seg.reset()
                with self.frames.mutex:
                    self.frames.queue.clear()

    def _check_timeout(self) -> None:
        if self.state == "listening" and time.time() > self.awake_until:
            self._set_state("idle")

    def _handle_utterance(self, audio: np.ndarray) -> None:
        awake = self.state == "listening" and time.time() <= self.awake_until
        if not awake:
            if not self.cfg.wake_enabled:
                return
            heard = self.wake_stt.transcribe(audio)
            woke, rest = match_wake(heard, self.rt.cfg.assistant.wake_words)
            if not woke:
                return
            if len(rest.split()) < 2:
                self._wake(play=True)  # "Nova." -> chime, then listen
                return
            full = self.stt.transcribe(audio)
            _, command = match_wake(full, self.rt.cfg.assistant.wake_words)
            command = command or rest
        else:
            command = self.stt.transcribe(audio)
            woke, rest = match_wake(command, self.rt.cfg.assistant.wake_words)
            if woke and rest:
                command = rest
        command = command.strip()
        if len(command) < 2 or command.lower() in {"thank you.", "thanks.", "you"}:
            self._set_state("idle")  # whisper's favourite hallucinations on noise
            return
        self._emit({"type": "transcript", "text": command})
        self._set_state("thinking")
        fut = asyncio.run_coroutine_threadsafe(self.rt.ask(command, channel="voice"), self.loop)
        reply = fut.result(timeout=self.rt.cfg.llm.timeout_s + 30)
        self.say(reply)
        self._wake(play=False)  # follow-up window: no wake word needed

    def say(self, text: str) -> None:
        spoken = for_speech(text)
        if not spoken:
            return
        self._set_state("speaking")
        try:
            self.tts.speak(spoken, on_level=lambda v: self._emit({"type": "level", "source": "tts", "value": min(1.0, v)}),
                           device=self.cfg.output_device)
        except Exception as e:  # noqa: BLE001
            log.error("TTS failed: %s", e)
        finally:
            self._set_state("idle")

    # ---------- events ----------
    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._emit({"type": "state", "state": state})

    def _emit(self, ev: dict) -> None:
        try:
            self.loop.call_soon_threadsafe(self.rt.bus.publish_nowait, ev)
        except RuntimeError:
            pass
