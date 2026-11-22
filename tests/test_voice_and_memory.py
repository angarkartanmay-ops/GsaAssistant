import time

import numpy as np
import pytest

from malice.brain.memory import Memory
from malice.voice.fx import chime, menace_fx
from malice.voice.tts import parse_blend, split_sentences
from malice.voice.vad import EnergyVAD, Segmenter


def test_blend_parsing_normalises():
    b = parse_blend("am_onyx:3, am_michael:1")
    assert b == [("am_onyx", 0.75), ("am_michael", 0.25)]


def test_sentence_split_keeps_long_sentences_bounded():
    parts = split_sentences("Short one. " + "word, " * 80 + "end.")
    assert parts[0] == "Short one." and all(len(p) <= 221 for p in parts)


def test_fx_is_bypassed_at_zero_and_bounded_otherwise():
    sr = 24000
    x = (0.3 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
    assert np.array_equal(menace_fx(x, sr, 0), x)
    y = menace_fx(x, sr, 2.0)
    assert y.dtype == np.float32 and np.abs(y).max() <= 0.9 and len(y) >= sr * 0.95
    assert len(chime()) > 0


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
    from malice.tools.core import remind_me
    rt = make_rt()
    out = await remind_me(rt, "in 20 minutes", "check the form")
    assert out.startswith("Reminder #") and rt.memory.upcoming_reminders(3600)
