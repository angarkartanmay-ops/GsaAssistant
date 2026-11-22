from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

import pytest

from nova.config import Config


class FakeLLM:
    """Scripted stand-in for Ollama.

    `script` is a list of responses for stream_chat/chat calls, in order. Each item is a str
    (plain reply) or {"tool": name, "args": {...}} (a tool call). `completer` answers
    complete() calls (used by digests, extraction, polishing).
    """

    def __init__(self, script: Optional[list] = None, completer: Optional[Callable[[str], str]] = None):
        self.script = list(script or [])
        self.completer = completer or (lambda prompt: "ok")
        self.calls: list[dict] = []
        self.model = "fake"

    def _next(self) -> Any:
        return self.script.pop(0) if self.script else "Done."

    async def health(self) -> dict:
        return {"ok": True, "models": ["fake"], "model_ready": True, "model": "fake"}

    async def stream_chat(self, messages, tools=None, temperature=None) -> AsyncIterator[dict]:  # noqa: ANN001
        self.calls.append({"messages": messages, "tools": tools})
        item = self._next()
        if isinstance(item, dict):
            yield {"tool_calls": [{"function": {"name": item["tool"], "arguments": item.get("args", {})}}]}
        else:
            for word in str(item).split(" "):
                yield {"content": word + " "}

    async def chat(self, messages, tools=None, json_mode=False, temperature=None) -> dict:  # noqa: ANN001
        self.calls.append({"messages": messages, "tools": tools})
        item = self._next()
        return {"content": item if isinstance(item, str) else json.dumps(item), "tool_calls": []}

    async def complete(self, prompt: str, system: str | None = None, json_mode: bool = False,
                       temperature=None) -> str:  # noqa: ANN001
        return self.completer(prompt)

    async def close(self) -> None:
        pass


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    import nova.config as mc
    monkeypatch.setattr(mc, "DATA_DIR", tmp_path)
    c = Config()
    c.discord.token = ""
    c.gmail.address = ""
    c.voice.enabled = False
    c.scheduler.enabled = False
    c.safety.allowed_dirs = [str(tmp_path)]
    return c


@pytest.fixture
def make_rt(cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nova.runtime import Runtime

    monkeypatch.setattr(Config, "db_path", property(lambda self: tmp_path / "test.db"))

    def _make(script=None, completer=None) -> Runtime:
        return Runtime(cfg, llm=FakeLLM(script, completer))
    return _make
