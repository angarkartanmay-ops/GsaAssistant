import pytest

from malice.brain.antislop import find_slop, for_speech, light_clean, polish


def test_detects_common_slop():
    text = ("Certainly! I hope this email finds you well. Let's delve into the details, "
            "it's important to note the deadline.")
    labels = {h.label for h in find_slop(text)}
    assert {"sycophantic opener", "hope this finds you well", "delve", "it's important to note"} <= labels


def test_clean_text_has_no_hits():
    assert find_slop("Report is due Friday 5pm. I'll send the photos tonight.") == []


def test_light_clean_strips_opener_and_closer():
    out = light_clean("Certainly! The report is due Friday. Let me know if you need anything else!")
    assert out == "The report is due Friday."


def test_light_clean_keeps_meaning_when_nothing_to_fix():
    s = "Three mails. One needs a reply by Thursday."
    assert light_clean(s) == s


def test_em_dash_chain_flattened():
    out = light_clean("Workshop — Friday — room 204 — bring laptops")
    assert "—" not in out


def test_for_speech_strips_markdown_and_urls():
    out = for_speech("**Deadline:** submit at https://example.com/form\n- item one\n- item two")
    assert "*" not in out and "http" not in out and "the link" in out


@pytest.mark.asyncio
async def test_polish_rewrites_only_when_needed():
    class L:
        calls = 0

        async def complete(self, prompt, system=None, temperature=None, json_mode=False):
            L.calls += 1
            return "Hey all, the Gemini workshop is on Friday at 4pm in room 204."

    clean = await polish("Workshop is Friday 4pm, room 204.", L(), "rules")
    assert clean == "Workshop is Friday 4pm, room 204." and L.calls == 0
    out = await polish("I hope this message finds you well! Let's delve into the vibrant Gemini workshop on Friday.",
                       L(), "rules")
    assert L.calls == 1 and "delve" not in out and "Friday" in out
