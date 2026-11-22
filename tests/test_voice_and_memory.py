import time

import numpy as np
import pytest

from nova.brain.memory import Memory
from nova.voice.fx import chime, normalize
from nova.voice.tts import parse_blend, split_sentences
from nova.voice.vad import EnergyVAD, Segmenter


def test_blend_parsing_normalises():
    b = parse_blend("bf_emma:3, bf_isabella:1")
    assert b == [("bf_emma", 0.75), ("bf_isabella", 0.25)]


def test_sentence_split_keeps_long_sentences_bounded():
    parts = split_sentences("Short one. " + "word, " * 80 + "end.")
    assert parts[0] == "Short one." and all(len(p) <= 221 for p in parts)


def test_voice_is_clean_no_effects_chain():
    import nova.voice.fx as fx
    from nova.config import VoiceCfg
    assert not hasattr(fx, "menace_fx") and "menace" not in VoiceCfg.model_fields
    cfg = VoiceCfg()
    assert cfg.tts_voice.startswith("bf_") and cfg.tts_lang == "en-gb"
    x = (0.3 * np.sin(np.arange(2400) / 5)).astype(np.float32)
    assert abs(float(np.abs(normalize(x)).max()) - 0.89) < 1e-3
    assert len(chime()) > 0


def test_persona_calls_him_sir():
    from nova.brain.persona import GREETINGS, system_prompt
    from nova.config import Config
    p = system_prompt(Config(), [], "text")
    assert 'Address him as "Sir"' in p and "FRIDAY" not in p
    assert all("{address}" in g for g in GREETINGS)


def test_segmenter_emits_one_utterance():
    seg = Segmenter(EnergyVAD(), threshold=0.5, silence_ms=320, min_speech_ms=96)
    rng = np.random.default_rng(0)
    quiet = lambda: (rng.standard_normal(512) * 0.002).astype(np.float32)  # noqa: E731
    loud = lambda: (np.sin(np.arange(512) / 3) * 0.3).astype(np.float32)  # noqa: E731
    outs = []
    for f in [quiet() for _ in range(60)] + [loud() for _ in range(20)] + [quiet() for _ in range(30)]:
        u = seg.feed(f)
        if u is not None:
            outs.append(u)
    assert len(outs) == 1 and len(outs[0]) >= 20 * 512


def test_memory_tasks_reminders_seen(tmp_path):
    m = Memory(tmp_path / "m.db")
    tid, created = m.upsert_task("dashboard", "k1", "Host workshop", "2026-11-30")
    assert created
    _, created_again = m.upsert_task("dashboard", "k1", "Host workshop", "2026-12-01")
    assert not created_again and m.tasks()[0].due == "2026-12-01"
    m.set_task_status(tid, "done")
    assert m.tasks() == [] and len(m.tasks(include_done=True)) == 1
    assert m.mark_seen("gmail", "1") and not m.mark_seen("gmail", "1")
    rid = m.add_reminder(time.time() - 1, "call Riya")
    assert m.due_reminders()[0][0] == rid
    m.finish_reminder(rid)
    assert m.due_reminders() == []
    m.remember("Riya is my co-lead")
    assert "Riya is my co-lead" in m.facts()


@pytest.mark.asyncio
async def test_reminder_tool_parses_natural_time(make_rt):
    from nova.tools.core import remind_me
    rt = make_rt()
    out = await remind_me(rt, "in 20 minutes", "check the form")
    assert out.startswith("Reminder #") and rt.memory.upcoming_reminders(3600)
