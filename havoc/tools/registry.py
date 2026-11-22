"""Tool registry: @tool decorator -> Ollama/OpenAI style JSON schema + dispatch.

Every tool takes `ctx` (the runtime) as its first argument; it is hidden from the LLM.
`confirm` can be a bool or a callable(ctx, **args) -> bool deciding whether this specific
call must wait for the user's yes/no before it runs.
"""
from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union, get_args, get_origin, get_type_hints

log = logging.getLogger("havoc.tools")

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
MAX_RESULT_CHARS = 3500


@dataclass
class Tool:
    name: str
    description: str
    func: Callable
    params: dict[str, str] = field(default_factory=dict)
    confirm: Union[bool, Callable[..., bool]] = False
    preview: Optional[Callable[..., str]] = None
    group: str = "general"
    # Optional async hook (ctx, args) -> args run before staging/executing, e.g. to polish
    # a message so the preview the user approves is exactly what gets sent.
    prepare: Optional[Callable[..., Any]] = None

    def schema(self) -> dict:
        sig = inspect.signature(self.func)
        hints = get_type_hints(self.func)
        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in list(sig.parameters.items())[1:]:  # skip ctx
            hint = hints.get(pname, str)
            if get_origin(hint) is Union:  # Optional[X]
                hint = next((a for a in get_args(hint) if a is not type(None)), str)
            jtype = _PY_TO_JSON.get(get_origin(hint) or hint, "string")
            prop: dict[str, Any] = {"type": jtype}
            if jtype == "array":
                prop["items"] = {"type": "string"}
            if pname in self.params:
                prop["description"] = self.params[pname]
            if p.default is inspect.Parameter.empty:
                required.append(pname)
            else:
                prop["description"] = (prop.get("description", "") + f" (default: {p.default!r})").strip()
            props[pname] = prop
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    def needs_confirm(self, ctx: Any, args: dict) -> bool:
        if callable(self.confirm):
            try:
                return bool(self.confirm(ctx, **args))
            except Exception:  # noqa: BLE001
                return True
        return bool(self.confirm)

    def describe_call(self, ctx: Any, args: dict) -> str:
        if self.preview:
            try:
                return self.preview(ctx, **args)
            except Exception:  # noqa: BLE001
                pass
        return f"{self.name}({json.dumps(args, ensure_ascii=False)})"


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def add(self, t: Tool) -> None:
        self.tools[t.name] = t

    def schemas(self, enabled_groups: Optional[set[str]] = None) -> list[dict]:
        return [t.schema() for t in self.tools.values()
                if enabled_groups is None or t.group in enabled_groups]

    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    async def call(self, ctx: Any, name: str, args: dict) -> str:
        t = self.tools.get(name)
        if not t:
            return f"ERROR: unknown tool {name!r}."
        args = _coerce_args(t, args or {})
        try:
            result = t.func(ctx, **args)
            if inspect.isawaitable(result):
                result = await result
        except TypeError as e:
            return f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:  # noqa: BLE001
            log.exception("tool %s failed", name)
            return f"ERROR: {name} failed: {type(e).__name__}: {e}"
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n...[truncated]"
        return text


def _coerce_args(t: Tool, args: dict) -> dict:
    """Small models sometimes send "7" for ints or "true" for bools; fix that."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {}
    hints = get_type_hints(t.func)
    sig = inspect.signature(t.func)
    out = {}
    for k, v in args.items():
        if k not in sig.parameters:
            continue  # drop hallucinated params
        hint = hints.get(k, str)
        if get_origin(hint) is Union:
            hint = next((a for a in get_args(hint) if a is not type(None)), str)
        try:
            if hint is int and not isinstance(v, int):
                v = int(float(v))
            elif hint is float and not isinstance(v, float):
                v = float(v)
            elif hint is bool and not isinstance(v, bool):
                v = str(v).strip().lower() in ("1", "true", "yes", "y")
            elif (hint is list or get_origin(hint) is list) and not isinstance(v, list):
                v = [x.strip() for x in str(v).split(",") if x.strip()] if v else []
            elif hint is str and not isinstance(v, str):
                v = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        except (TypeError, ValueError):
            pass
        out[k] = v
    return out


REGISTRY = Registry()


def tool(name: str, description: str, params: Optional[dict[str, str]] = None,
         confirm: Union[bool, Callable[..., bool]] = False, preview: Optional[Callable[..., str]] = None,
         group: str = "general", prepare: Optional[Callable[..., Any]] = None):
    def deco(fn: Callable) -> Callable:
        REGISTRY.add(Tool(name, description, fn, params or {}, confirm, preview, group, prepare))
        return fn
    return deco


async def prepare_args(t: Tool, ctx: Any, args: dict) -> dict:
    args = _coerce_args(t, args or {})
    if t.prepare is None:
        return args
    try:
        out = t.prepare(ctx, args)
        if inspect.isawaitable(out):
            out = await out
        return out or args
    except Exception:  # noqa: BLE001
        log.warning("prepare hook for %s failed", t.name, exc_info=True)
        return args
