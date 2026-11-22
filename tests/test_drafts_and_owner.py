"""Draft-mode email (ready-to-send Gmail compose links), and Discord owner/channel resolution."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from havoc.config import DiscordCfg, GmailCfg
from havoc.connectors.gmail_imap import GmailClient


def test_compose_url_opens_in_the_sending_account():
    g = GmailClient(GmailCfg(address="me@gmail.com", official_address="tanmay.cs25@rvce.edu.in"))
    url = g.compose_url("a@x.com", "Gemini workshop, Friday 4pm", "Hi all,\nSee you there & bring laptops.", bcc="s1@rvce.edu.in,s2@rvce.edu.in")
    u = urlparse(url)
    q = parse_qs(u.query)
    assert u.netloc == "mail.google.com" and q["authuser"] == ["tanmay.cs25@rvce.edu.in"]
    assert q["view"] == ["cm"] and q["to"] == ["a@x.com"] and q["bcc"] == ["s1@rvce.edu.in,s2@rvce.edu.in"]
    assert q["su"] == ["Gemini workshop, Friday 4pm"]
    assert q["body"] == ["Hi all,\nSee you there & bring laptops."]  # newlines and & survive


@pytest.mark.asyncio
async def test_send_email_in_draft_mode_never_sends(make_rt, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    rt = make_rt([{"tool": "send_email", "args": {"to": "", "bcc": "first@rvce.edu.in,second@rvce.edu.in",
                                                  "subject": "Gemini workshop", "body": "Hi all, it's on Friday at 4pm."}},
                  "Draft's open, Sir."])
    rt.cfg.gmail.send_mode = "draft"
    rt.cfg.gmail.official_address = "tanmay.cs25@rvce.edu.in"
    rt.cfg.gmail.signature = "Tanmay Angarkar\nGoogle Student Ambassador"
    rt.cfg.safety.confirm_email_send = True  # draft mode needs no confirmation: nothing goes out
    rt.gmail.send = lambda msg: (_ for _ in ()).throw(AssertionError("draft mode must not send"))
    await rt.ask("email the workshop details to the students, bcc them")
    assert rt.agent.pending is None and len(opened) == 1
    q = parse_qs(urlparse(opened[0]).query)
    assert q["bcc"] == ["first@rvce.edu.in,second@rvce.edu.in"]
    assert q["body"][0].endswith("Tanmay Angarkar\nGoogle Student Ambassador")
    tool_result = [m for m in rt.llm.calls[-1]["messages"] if m["role"] == "tool"][-1]["content"]
    assert "Draft ready in tanmay.cs25@rvce.edu.in" in tool_result and "press Send" in tool_result


@pytest.mark.asyncio
async def test_draft_link_is_not_opened_on_the_pc_when_asked_from_the_phone(make_rt, monkeypatch):
    from havoc.tools.gmail import open_draft
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    rt = make_rt()
    rt.current_channel = "discord-dm"
    out = open_draft(rt, "poc@google.com", "Report", "Attached.")
    assert opened == [] and "https://mail.google.com/mail/" in out


def test_signature_added_once(make_rt):
    from havoc.tools.gmail import with_signature
    rt = make_rt()
    rt.cfg.gmail.signature = "Tanmay Angarkar\nGoogle Student Ambassador"
    once = with_signature(rt, "See you Friday.")
    assert once == "See you Friday.\n\nTanmay Angarkar\nGoogle Student Ambassador"
    assert with_signature(rt, once) == once


def test_discord_owner_locks_to_first_matching_username(cfg, tmp_path, monkeypatch):
    import havoc.config as mc
    from havoc.connectors.discord_bot import DiscordConnector
    monkeypatch.setattr(mc, "DATA_DIR", tmp_path)
    dc = DiscordConnector(DiscordCfg(owner_username="tanmay_7697"))
    stranger = SimpleNamespace(id=111, name="someone_else")
    me = SimpleNamespace(id=4242, name="Tanmay_7697")
    imposter = SimpleNamespace(id=999, name="tanmay_7697")  # same name later, different account
    assert not dc.is_owner(stranger)
    assert dc.is_owner(me) and dc.owner_id == 4242
    assert not dc.is_owner(imposter)
    assert dc.is_owner(SimpleNamespace(id=4242, name="renamed"))  # ID wins after the lock


@pytest.mark.asyncio
async def test_discord_channel_by_id_or_link(cfg):
    from havoc.connectors.discord_bot import DiscordConnector, DiscordError
    general = SimpleNamespace(id=1571025488242016316, name="general", send=lambda *a, **k: None)
    guild = SimpleNamespace(text_channels=[general], get_channel=lambda i: general if i == general.id else None)
    dc = DiscordConnector(DiscordCfg(default_channel="1571025488242016316"))

    async def g():
        return guild
    dc._guild = g
    assert await dc._channel("") is general  # default channel given as an ID
    assert await dc._channel("https://discord.com/channels/1571016845060735047/1571025488242016316") is general
    assert await dc._channel("#general") is general
    with pytest.raises(DiscordError):
        await dc._channel("1571025488242019999")
