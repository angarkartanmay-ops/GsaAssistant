"""Web search (DuckDuckGo, no key) and page reading."""
from __future__ import annotations

from typing import Any

import httpx

from ..connectors.gmail_imap import html_to_text
from .common import blocking
from .registry import tool


def _ddg(query: str, n: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:  # older package name
        from duckduckgo_search import DDGS  # type: ignore[no-redef]
    with DDGS() as d:
        return list(d.text(query, max_results=n))


@tool("web_search", "Search the web.", params={"query": "Search terms", "max_results": "How many results"},
      group="web")
async def web_search(rt: Any, query: str, max_results: int = 5) -> str:
    results = await blocking(_ddg, query, max(1, min(max_results, 10)))
    if not results:
        return "No results."
    return "\n\n".join(f"{r.get('title')}\n{r.get('href')}\n{r.get('body', '')[:300]}" for r in results)


@tool("read_webpage", "Fetch a web page and return its text.", params={"url": "Full URL"}, group="web")
async def read_webpage(rt: Any, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with httpx.AsyncClient(follow_redirects=True, timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}) as c:
        r = await c.get(url)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    text = html_to_text(r.text) if "html" in ctype else r.text
    return f"{url}\n\n{text[:3200]}"
