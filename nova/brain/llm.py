"""Thin async client for Ollama's /api/chat with tool calling and streaming."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx

from ..config import LLMCfg

log = logging.getLogger("nova.llm")


class LLMError(RuntimeError):
    pass


class OllamaLLM:
    def __init__(self, cfg: LLMCfg):
        self.cfg = cfg
        self.model = cfg.model
        self._client = httpx.AsyncClient(base_url=cfg.host, timeout=cfg.timeout_s)

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict:
        """Returns {'ok': bool, 'models': [...], 'model_ready': bool}."""
        try:
            r = await self._client.get("/api/tags", timeout=5)
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e), "models": [], "model_ready": False}
        ready = any(n == self.model or n.split(":")[0] == self.model.split(":")[0] and
                    n.endswith(self.model.split(":")[-1]) for n in names)
        if not ready and self.cfg.fallback_model in names:
            log.warning("Model %s not pulled; falling back to %s", self.model, self.cfg.fallback_model)
            self.model = self.cfg.fallback_model
            ready = True
        return {"ok": True, "models": names, "model_ready": ready, "model": self.model}

    def _payload(self, messages: list[dict], tools: Optional[list[dict]], stream: bool,
                 json_mode: bool, temperature: Optional[float]) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "think": False,  # qwen3: skip the hidden reasoning pass, much faster replies
            "keep_alive": "30m",
            "options": {
                "temperature": self.cfg.temperature if temperature is None else temperature,
                "num_ctx": self.cfg.num_ctx,
            },
        }
        if tools:
            body["tools"] = tools
        if json_mode:
            body["format"] = "json"
        return body

    async def chat(self, messages: list[dict], tools: Optional[list[dict]] = None,
                   json_mode: bool = False, temperature: Optional[float] = None) -> dict:
        """Non-streaming call. Returns {'content': str, 'tool_calls': list}."""
        try:
            r = await self._client.post("/api/chat", json=self._payload(messages, tools, False, json_mode, temperature))
            if r.status_code == 400 and "think" in r.text:
                # Older Ollama without the think flag.
                body = self._payload(messages, tools, False, json_mode, temperature)
                body.pop("think", None)
                r = await self._client.post("/api/chat", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed: {e}") from e
        msg = r.json().get("message", {})
        return {"content": strip_think(msg.get("content", "")), "tool_calls": msg.get("tool_calls") or []}

    async def stream_chat(self, messages: list[dict], tools: Optional[list[dict]] = None,
                          temperature: Optional[float] = None) -> AsyncIterator[dict]:
        """Yields {'content': delta} and {'tool_calls': [...]} chunks."""
        body = self._payload(messages, tools, True, False, temperature)
        try:
            async with self._client.stream("POST", "/api/chat", json=body) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode(errors="ignore")
                    raise LLMError(f"Ollama error {r.status_code}: {text[:300]}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMError(data["error"])
                    msg = data.get("message", {})
                    if msg.get("tool_calls"):
                        yield {"tool_calls": msg["tool_calls"]}
                    if msg.get("content"):
                        yield {"content": msg["content"]}
                    if data.get("done"):
                        break
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed: {e}") from e

    async def complete(self, prompt: str, system: str | None = None, json_mode: bool = False,
                       temperature: Optional[float] = None) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return (await self.chat(msgs, json_mode=json_mode, temperature=temperature))["content"]


def strip_think(text: str) -> str:
    """Remove any <think>...</think> block a reasoning model leaks into content."""
    import re
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).strip() if "<think>" in text else text


def parse_json_loose(text: str) -> Any:
    """Parse JSON from model output that may be wrapped in prose or code fences."""
    import re
    text = strip_think(text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No JSON found in model output: {text[:200]!r}")
