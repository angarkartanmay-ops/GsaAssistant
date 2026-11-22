"""The agent loop: persona prompt + history + routed tools -> Ollama, with a confirm gate."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ..tools.registry import REGISTRY, Registry, prepare_args
from .antislop import ensure_address, light_clean
from .llm import LLMError
from .persona import system_prompt

log = logging.getLogger("havoc.agent")

Emit = Callable[[dict], Awaitable[None]]
MAX_STEPS = 6

YES_RE = re.compile(r"^\s*(yes|yeah|yea|yep|yup|y|sure|do it|send( it)?|post( it)?|go( ahead)?|"
                    r"confirm(ed)?|ok(ay)?|affirmative|proceed|ship it|approved?)\b", re.I)
CONFIRM_VERBS = {"discord_post": "Post it", "wa_send": "Send it", "send_reply": "Send it",
                 "send_email": "Send it", "run_powershell": "Run it", "write_file": "Overwrite it",
                 "power_action": "Go ahead"}
PROMISE_RE = re.compile(r"\b(i'?ll|i will|let me|i'?m going to|allow me to)\s+(now\s+)?(check|look|scan|fetch|"
                        r"pull|see|search|read|go through|find|get|open|grab|review)\b", re.I)
NO_RE = re.compile(r"^\s*(no|nope|nah|n|cancel|stop|don'?t|abort|hold on|wait|scrap( that| it)?)\b", re.I)

# Keyword routing keeps the tool list small so an 8B model stays accurate and fast.
ROUTES: dict[str, list[str]] = {
    "mail": ["mail", "email", "inbox", "gmail", "reply", "draft", "sender", "unread"],
    "dashboard": ["dashboard", "portal", "webapp", "web app", "task", "points", "engagement",
                  "report", "submission", "deadline", "due", "todo", "to-do"],
    "discord": ["discord", "server", "channel", "batch", "announce"],
    "whatsapp": ["whatsapp", "wa ", "group", "gc", "chat", "message"],
    "pc": ["open", "launch", "file", "folder", "powershell", "command", "run ", "volume", "pause",
           "play", "music", "screen", "lock", "shutdown", "restart", "cpu", "gpu", "ram", "battery",
           "system", "clipboard", "app", "notepad", "chrome", "edge", "vs code", "spotify"],
    "web": ["search", "google", "look up", "lookup", "web", "website", "news", "http", "www", "find out"],
}
CORE_GROUPS = {"core"}

# Questions about his real data must be answered from a tool, never from the model's imagination.
ACTION_RE = re.compile(r"\b(post|send|tell|share|reply|draft|write|email|add|remind|delete|undo|open|run|"
                       r"mark|forward|announce|schedule|remember|forget|set|create|make)\b", re.I)
GROUND_KEYS: list[tuple[str, tuple[str, ...]]] = [
    ("wa_read", ("whatsapp", "wa group", "wa gc", " gc", "group chat")),
    ("discord_read", ("discord",)),
    ("gsa_mail_digest", ("mail", "inbox", "gmail")),
    ("dashboard_tasks", ("dashboard", "task", "deadline", " due", "points", "engagement")),
]
BRIEF_KEYS = ("brief", "catch me up", "what did i miss", "update me", "anything new", "what's new",
              "whats new", "worry", "my day", "today", "what's up", "whats up", "anything i should")


def grounding_tool(text: str) -> Optional[str]:
    """The read tool a question about his data must be answered from, or None."""
    low = f" {text.lower()} "
    if ACTION_RE.search(low):
        return None  # requests to do something; the model picks the action tool itself
    for tool_name, keys in GROUND_KEYS:
        if any(k in low for k in keys):
            return tool_name
    if any(k in low for k in BRIEF_KEYS):
        return "daily_briefing"
    return None


def route_groups(text: str) -> Optional[set[str]]:
    low = f" {text.lower()} "
    groups = {g for g, kws in ROUTES.items() if any(k in low for k in kws)}
    if any(w in low for w in ("brief", "summary", "summar", "catch me up", "what did i miss", "update me",
                              "anything new", "what's new", "worry", "my day", "anything i should")):
        groups |= {"mail", "dashboard", "discord", "whatsapp"}
    if not groups:
        return None  # nothing obvious: offer every tool
    return groups | CORE_GROUPS


@dataclass
class Pending:
    tool: str
    args: dict
    preview: str


class Agent:
    def __init__(self, rt: Any, registry: Registry = REGISTRY):
        self.rt = rt
        self.registry = registry
        self.pending: Optional[Pending] = None
        self.lock = asyncio.Lock()
        self.history: list[dict] = rt.memory.recent_messages(rt.cfg.llm.history_turns)

    def _trim_history(self) -> None:
        limit = self.rt.cfg.llm.history_turns * 3
        if len(self.history) > limit:
            self.history = self.history[-limit:]
        # Never start the window on an orphaned tool result or tool-call message.
        while self.history and (self.history[0]["role"] in ("tool", "system")
                                or self.history[0].get("tool_calls")):
            self.history.pop(0)

    async def respond(self, text: str, channel: str = "text", emit: Optional[Emit] = None) -> str:
        async def _emit(ev: dict) -> None:
            if emit:
                try:
                    await emit(ev)
                except Exception:  # noqa: BLE001
                    log.debug("emit failed", exc_info=True)

        # Saved straight away (not after the reply) so a device opened mid-turn already sees it.
        self.rt.memory.add_message("user", text, channel)
        async with self.lock:
            await _emit({"type": "state", "state": "thinking"})
            try:
                reply = await self._respond(text, channel, _emit)
            except LLMError as e:
                reply = (f"My language core isn't answering ({e}). Check that Ollama is running "
                         f"and the model is pulled: `ollama pull {self.rt.cfg.llm.model}`.")
            except Exception as e:  # noqa: BLE001
                log.exception("agent failure")
                reply = f"Something in me broke: {type(e).__name__}: {e}. The log has the details."
            reply = ensure_address(light_clean(reply), self.rt.cfg.assistant.address_as)
            self.rt.memory.add_message("assistant", reply, channel)
            await _emit({"type": "final", "text": reply, "pending": self._pending_view()})
            await _emit({"type": "state", "state": "idle"})
            return reply

    def _pending_view(self) -> Optional[dict]:
        if not self.pending:
            return None
        return {"tool": self.pending.tool, "preview": self.pending.preview}

    async def _respond(self, text: str, channel: str, emit: Emit) -> str:
        note: Optional[str] = None
        if self.pending:
            p = self.pending
            if YES_RE.match(text):
                # Run it and report the result directly. Handing control back to the model
                # here invites it to "helpfully" stage the same action a second time.
                self.pending = None
                await emit({"type": "tool", "name": p.tool, "status": "running"})
                result = await self.registry.call(self.rt, p.tool, p.args)
                await emit({"type": "tool", "name": p.tool, "status": "done"})
                reply = (f"That didn't go through. {result}" if result.startswith("ERROR")
                         else f"Done. {result}")
                self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
                return reply
            elif NO_RE.match(text):
                self.pending = None
                return "Cancelled. Nothing went out, and the batch remains blissfully unaware."
            else:
                self.pending = None
                note = "The previously staged action was discarded because the user said something else."

        groups = route_groups(text)
        tools = self.registry.schemas(groups)
        sys = system_prompt(self.rt.cfg, self.rt.memory.facts(), channel)
        self.history.append({"role": "user", "content": text})
        if note:
            self.history.append({"role": "system", "content": note})
        self._trim_history()

        nudged = False
        used_tools = False
        must_ground = grounding_tool(text)
        for _step in range(MAX_STEPS):
            messages = [{"role": "system", "content": sys}] + self.history
            content, calls = "", []
            async for chunk in self.rt.llm.stream_chat(messages, tools=tools or None):
                if "content" in chunk:
                    content += chunk["content"]
                    await emit({"type": "token", "text": chunk["content"]})
                if "tool_calls" in chunk:
                    calls.extend(chunk["tool_calls"])
            if not calls:
                ungrounded = bool(must_ground) and not used_tools and self.registry.get(must_ground) is not None
                if tools and not used_tools and not nudged and (ungrounded or PROMISE_RE.search(content)):
                    # Small models like to announce "I'll check", or answer from imagination.
                    nudged = True
                    await emit({"type": "retract"})
                    self.history.append({"role": "system", "content":
                                         "You haven't checked anything yet. Call the right tool now, then "
                                         "answer only from its result."})
                    continue
                if ungrounded:
                    # Still guessing after a nudge: fetch the facts ourselves and answer from them.
                    await emit({"type": "retract"})
                    return await self._forced_answer(sys, must_ground, emit)
                self.history.append({"role": "assistant", "content": content})
                return content.strip() or "Done."
            used_tools = True

            self.history.append({"role": "assistant", "content": content, "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = await self._run_tool(name, args, emit)
                self.history.append({"role": "tool", "content": result, "tool_name": name})
            if self.pending:
                # Deterministic question: the user must approve exactly this text, and small
                # models tend to paraphrase or echo internal instructions.
                verb = CONFIRM_VERBS.get(self.pending.tool, "Do it")
                q = f"Ready when you are:\n\n{self.pending.preview}\n\n{verb}? Say yes, or tell me what to change."
                self.history.append({"role": "assistant", "content": q})
                return q
        return "I went in circles on that one. Rephrase it and I'll try being slightly less clever."

    async def _forced_answer(self, sys: str, tool_name: str, emit: Emit) -> str:
        result = await self._run_tool(tool_name, {}, emit)
        self.history.append({"role": "assistant", "content": "",
                             "tool_calls": [{"function": {"name": tool_name, "arguments": {}}}]})
        self.history.append({"role": "tool", "content": result, "tool_name": tool_name})
        self.history.append({"role": "system", "content": "Answer the user's question using only the tool "
                                                          "result above. Do not add anything it doesn't say."})
        out = await self.rt.llm.chat([{"role": "system", "content": sys}] + self.history)
        content = out["content"].strip() or result
        self.history.append({"role": "assistant", "content": content})
        return content

    async def _run_tool(self, name: str, args: dict, emit: Emit) -> str:
        t = self.registry.get(name)
        if t is None:
            return f"ERROR: no tool named {name}. Available: {', '.join(self.registry.tools)}"
        args = await prepare_args(t, self.rt, args)
        if t.needs_confirm(self.rt, args):
            preview = t.describe_call(self.rt, args)
            self.pending = Pending(name, args, preview)
            await emit({"type": "confirm", "tool": name, "preview": preview})
            return ("STAGED, NOT EXECUTED. It runs only if the user says yes. Show the user this "
                    f"preview and ask a short yes/no question:\n{preview}")
        await emit({"type": "tool", "name": name, "status": "running", "args": args})
        result = await self.registry.call(self.rt, name, args)
        await emit({"type": "tool", "name": name, "status": "done"})
        return result

    def reset(self) -> None:
        self.history.clear()
        self.pending = None
        self.rt.memory.clear_history()
