import json
from email.message import EmailMessage

import httpx
import pytest

from malice.config import WhatsAppCfg
from malice.connectors.gmail_imap import Mail, parse_fetch
from malice.connectors.whatsapp_client import WhatsAppClient, WhatsAppError
from malice.voice.wake import match_wake


def _raw_mail(subject, body, sender="Program Team <gsa-team@google.com>"):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "tanmay@example.com"
    m["Subject"] = subject
    m["Date"] = "Fri, 20 Nov 2026 10:00:00 +0530"
    m["Message-ID"] = "<abc@google.com>"
    m.set_content(body)
    return m.as_bytes()


def test_parse_fetch_reads_imap_tuples():
    data = [(b'1 (UID 42 FLAGS (\\Seen) X-GM-MSGID 777 X-GM-THRID 778 X-GM-LABELS ("\\\\Inbox") BODY[] {123}',
             _raw_mail("October report due", "Please submit your October report by 25 Nov.\n\nOn Mon someone wrote:\n> old")),
            b")"]
    mails = parse_fetch(data)
    assert len(mails) == 1
    m = mails[0]
    assert (m.uid, m.msgid, m.thread_id) == ("42", "777", "778")
    assert m.subject == "October report due" and not m.unread
    assert "25 Nov" in m.body and "old" not in m.body


@pytest.mark.asyncio
async def test_mail_digest_groups_and_falls_back(make_rt):
    from malice.tools.gmail import format_digest, heuristic_digest

    def mk(i, sender, subject, body, unread=False):
        return Mail(uid=i, msgid="10" + i, thread_id="10" + i, sender=sender, to="", subject=subject,
                    date="Fri 20 Nov 10:00", body=body, unread=unread)
    mails = [mk("1", "Program <p@google.com>", "Submit event report by Friday", "Deadline Friday.", True),
             mk("2", "Newsletter <news@google.com>", "Monthly digest", "unsubscribe here"),
             mk("3", "Priya <priya@college.edu>", "Room for workshop?", "Could you confirm the room?")]
    items = heuristic_digest(mails)
    cats = {i["id"]: i["category"] for i in items}
    assert cats == {"101": "deadline", "102": "noise", "103": "action"}
    text = format_digest(items, mails)
    assert text.index("DEADLINES") < text.index("NEEDS YOUR ACTION") < text.index("NOISE")
    assert "[unread]" in text

    # With a working LLM, the LLM's classification is used.
    rt = make_rt(completer=lambda p: json.dumps({"items": [
        {"id": "101", "category": "deadline", "summary": "Event report due Friday", "due": "Fri"},
        {"id": "102", "category": "noise", "summary": "Newsletter", "due": None},
        {"id": "103", "category": "action", "summary": "Priya needs the room confirmed", "due": None}]}))
    rt.gmail.gsa_mails = lambda days, unread_only=False, limit=None: mails
    from malice.tools.gmail import gsa_mail_digest
    out = await gsa_mail_digest(rt, days=3)
    assert "Event report due Friday (due Fri)" in out and "Priya needs the room confirmed" in out


@pytest.mark.asyncio
async def test_dashboard_extraction_and_sync(make_rt):
    from malice.connectors.dashboard_browser import PageDump
    from malice.tools.dashboard import dashboard_tasks

    reply = json.dumps({"tasks": [
        {"title": "Host a Gemini learning session", "due": "2026-11-30", "status": "open", "points": "50", "link": None},
        {"title": "Submit photos from last event", "due": None, "status": "submitted", "points": None, "link": None}],
        "stats": "180/250 engagements this month"})
    rt = make_rt(completer=lambda p: reply)
    rt.cfg.dashboard.url = "https://example.test/dashboard"

    async def fake_read():
        return [PageDump("https://example.test/dashboard", "Ambassador", "Tasks ...", [])]
    rt.dashboard.read = fake_read
    out = await dashboard_tasks(rt, refresh=True)
    assert "2 item(s), 2 new" in out
    assert "180/250 engagements" in out
    assert "Host a Gemini learning session" in out
    assert "Submit photos" not in out.split("Progress")[1]  # submitted tasks hidden from the open list
    out2 = await dashboard_tasks(rt, refresh=True)
    assert "0 new" in out2


@pytest.mark.asyncio
async def test_whatsapp_client_against_mock_bridge():
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/status":
            return httpx.Response(200, json={"connected": True})
        if req.url.path == "/groups":
            return httpx.Response(200, json=[{"id": "1@g.us", "name": "GSA Batch '26 Official"},
                                             {"id": "2@g.us", "name": "Family"}])
        if req.url.path == "/messages":
            assert req.url.params["chat"] == "1@g.us"
            return httpx.Response(200, json=[{"id": "m1", "chat": "1@g.us", "chatName": "GSA", "sender": "Riya",
                                              "text": "Form closes tonight", "ts": 1763600000, "fromMe": False}])
        if req.url.path == "/send":
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    c = WhatsAppClient(WhatsAppCfg(group_name="gsa"), transport=httpx.MockTransport(handler))
    g, msgs = await c.messages(None, 24)
    assert g["name"].startswith("GSA") and msgs[0].text == "Form closes tonight"
    assert "Riya: Form closes tonight" in msgs[0].line()
    assert await c.send(None, "On it.") == "Sent to GSA Batch '26 Official."
    assert sent == {"chat": "1@g.us", "text": "On it."}
    with pytest.raises(WhatsAppError):
        await c.find_group("college football")


@pytest.mark.asyncio
async def test_whatsapp_bridge_down_gives_clear_error():
    def handler(req):
        raise httpx.ConnectError("refused")
    c = WhatsAppClient(WhatsAppCfg(), transport=httpx.MockTransport(handler))
    with pytest.raises(WhatsAppError, match="isn't running"):
        await c.status()


@pytest.mark.parametrize("heard,woke,rest", [
    ("Malice, summarise the GSA group.", True, "summarise the GSA group."),
    ("Hey Malice what's on my dashboard", True, "what's on my dashboard"),
    ("Mal ice brief me", True, "brief me"),
    ("Malis.", True, ""),
    ("I told Riya about the meeting", False, ""),
])
def test_wake_matching(heard, woke, rest):
    w, r = match_wake(heard, ["malice", "malis", "mallis", "malise", "alice"])
    assert w == woke and r == rest
