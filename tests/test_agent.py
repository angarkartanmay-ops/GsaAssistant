import pytest

from nova.brain.agent import route_groups
from nova.tools.registry import REGISTRY


def test_tool_schemas_are_valid():
    import nova.tools  # noqa: F401
    names = set(REGISTRY.tools)
    for expected in ["gsa_mail_digest", "dashboard_tasks", "discord_read", "discord_post", "wa_read",
                     "wa_send", "daily_briefing", "remind_me", "run_powershell", "open_app", "web_search"]:
        assert expected in names
    for s in REGISTRY.schemas():
        fn = s["function"]
        assert fn["name"] and fn["description"]
        assert "ctx" not in fn["parameters"]["properties"]
        assert "rt" not in fn["parameters"]["properties"]
        for r in fn["parameters"]["required"]:
            assert r in fn["parameters"]["properties"]


def test_routing_narrows_tools():
    assert "mail" in route_groups("summarise my gsa mail")
    assert "whatsapp" in route_groups("what's new in the whatsapp gc")
    assert route_groups("brief me") >= {"mail", "dashboard", "discord", "whatsapp"}
    assert route_groups("tell me a joke") is None  # unknown intent -> all tools


@pytest.mark.asyncio
async def test_plain_reply_is_cleaned_and_saved(make_rt):
    rt = make_rt(["Certainly! Your inbox is quiet."])
    reply = await rt.ask("anything new?")
    assert reply == "Your inbox is quiet, Sir."
    assert rt.memory.recent_messages()[-1]["content"] == "Your inbox is quiet, Sir."


@pytest.mark.asyncio
async def test_tool_call_loop(make_rt):
    rt = make_rt([{"tool": "add_task", "args": {"title": "Submit event photos", "due": "tomorrow 5pm"}},
                  "Added. Photos due tomorrow at five."])
    events = []

    async def emit(ev):
        events.append(ev)

    reply = await rt.agent.respond("remind me to submit event photos tomorrow 5pm as a task", emit=emit)
    assert "Photos due" in reply
    assert [t.title for t in rt.memory.tasks()] == ["Submit event photos"]
    assert any(e["type"] == "tool" and e["name"] == "add_task" for e in events)
    # The tool result was fed back to the model.
    last_msgs = rt.llm.calls[-1]["messages"]
    assert any(m["role"] == "tool" and "Submit event photos" in m["content"] for m in last_msgs)


@pytest.mark.asyncio
async def test_confirm_gate_stages_then_sends(make_rt):
    sent = []

    async def fake_post(channel, text, files=None):
        sent.append((channel, text))
        return f"Posted in #{channel}"

    rt = make_rt([{"tool": "discord_post", "args": {"channel": "general", "message": "Workshop moved to 5pm."}},
                  "Post this in #general: 'Workshop moved to 5pm.'? Yes or no.",
                  "Posted."])
    rt.discord.post = fake_post
    rt.cfg.safety.confirm_discord_post = True
    q = await rt.ask("tell the batch on discord the workshop moved to 5pm")
    assert "Workshop moved to 5pm." in q and "Post it?" in q
    assert sent == [] and rt.agent.pending is not None
    await rt.ask("yes")
    assert sent == [("general", "Workshop moved to 5pm.")]
    assert rt.agent.pending is None


@pytest.mark.asyncio
async def test_confirmed_action_runs_once_without_another_llm_turn(make_rt):
    sent = []

    async def fake_post(channel, text, files=None):
        sent.append(text)
        return f"Posted in #{channel}"

    rt = make_rt([{"tool": "discord_post", "args": {"channel": "general", "message": "Hall booked."}},
                  "Post it? Yes or no.",
                  # If the agent wrongly asked the model again, it would stage a second post:
                  {"tool": "discord_post", "args": {"channel": "general", "message": "Hall booked."}}])
    rt.discord.post = fake_post
    rt.cfg.safety.confirm_discord_post = True
    await rt.ask("tell discord the hall is booked")
    calls_before = len(rt.llm.calls)
    reply = await rt.ask("yes")
    assert reply == "Done, Sir. Posted in #general"
    assert sent == ["Hall booked."] and rt.agent.pending is None
    assert len(rt.llm.calls) == calls_before


@pytest.mark.asyncio
async def test_announcing_instead_of_acting_gets_nudged(make_rt):
    rt = make_rt(["I'll check the GSA WhatsApp group for you.",
                  {"tool": "list_tasks", "args": {}},
                  "No tasks on file, so nothing is due."])
    reply = await rt.ask("anything due?")
    assert reply == "No tasks on file, so nothing is due, Sir."


@pytest.mark.asyncio
async def test_confirm_gate_cancel(make_rt):
    rt = make_rt([{"tool": "discord_post", "args": {"channel": "general", "message": "hi"}}, "Send it?"])
    rt.cfg.safety.confirm_discord_post = True
    await rt.ask("post hi on discord")
    reply = await rt.ask("no")
    assert "Cancelled" in reply and rt.agent.pending is None


@pytest.mark.asyncio
async def test_whatsapp_send_is_auto_by_default(make_rt):
    sent = []

    async def fake_send(group, text, files=None):
        sent.append(text)
        return "Sent to GSA Batch 2026."

    rt = make_rt([{"tool": "wa_send", "args": {"message": "Form closes at 9pm tonight."}}, "Sent."])
    rt.whatsapp.send = fake_send
    await rt.ask("tell the whatsapp group the form closes at 9pm")
    assert sent == ["Form closes at 9pm tonight."]


@pytest.mark.asyncio
async def test_outbound_message_is_polished_before_staging(make_rt):
    rt = make_rt([{"tool": "discord_post",
                   "args": {"channel": "general", "message": "I hope this message finds you well! Let's delve into Friday's workshop."}},
                  "Send it?"],
                 completer=lambda p: "Friday's workshop is on, see you all there.")
    rt.cfg.safety.confirm_discord_post = True
    await rt.ask("post about the friday workshop in discord")
    assert rt.agent.pending.args["message"] == "Friday's workshop is on, see you all there."


@pytest.mark.asyncio
async def test_unknown_tool_does_not_crash(make_rt):
    rt = make_rt([{"tool": "make_coffee", "args": {}}, "I can't make coffee."])
    assert "coffee" in await rt.ask("make me coffee")


@pytest.mark.asyncio
async def test_shell_confirm_policy(make_rt):
    from nova.tools.system import shell_needs_confirm
    rt = make_rt()
    assert not shell_needs_confirm(rt, command="Get-Process | Select -First 5")
    assert shell_needs_confirm(rt, command="Remove-Item C:\\temp -Recurse")
    assert shell_needs_confirm(rt, command="Get-ChildItem; Remove-Item x")
