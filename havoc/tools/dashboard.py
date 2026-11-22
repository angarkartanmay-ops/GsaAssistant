"""Dashboard + task tools. Dashboard tasks and your own tasks live in one list."""
from __future__ import annotations

import difflib
import hashlib
import time
from typing import Any

import dateparser

from ..brain.llm import parse_json_loose
from .registry import tool

EXTRACT_PROMPT = """Below is the visible text of a Google Student Ambassador web app (dashboard).
Extract every task, mission, activity or deliverable the ambassador has to do or has done.
Return JSON: {"tasks":[{"title":"...","due":"YYYY-MM-DD or null","status":"open|done|submitted|overdue",
"points":"points/engagements if shown, else null","link":"URL from LINKS if one matches, else null"}],
"stats":"one line with any progress numbers shown (points, engagements, rank), or null"}.
Only include things that are actually on the page. Do not invent tasks.

"""


def task_key(title: str) -> str:
    return hashlib.sha1(title.strip().lower().encode()).hexdigest()[:16]


async def extract_tasks(rt: Any, page_text: str) -> dict:
    raw = await rt.llm.complete(EXTRACT_PROMPT + page_text[:10000], json_mode=True, temperature=0.0)
    data = parse_json_loose(raw)
    if isinstance(data, list):
        data = {"tasks": data, "stats": None}
    tasks = [t for t in data.get("tasks", []) if isinstance(t, dict) and t.get("title")]
    return {"tasks": tasks, "stats": data.get("stats")}


async def sync_dashboard(rt: Any) -> dict:
    """Read the dashboard, upsert its tasks, return {'new': [...], 'stats': str|None, 'count': n}."""
    dumps = await rt.dashboard.read()
    text = "\n\n".join(d.for_llm() for d in dumps)
    result = await extract_tasks(rt, text)
    new = []
    for t in result["tasks"]:
        status = str(t.get("status") or "open").lower()
        tid, created = rt.memory.upsert_task(
            "dashboard", task_key(t["title"]), t["title"].strip(), t.get("due") or None, status,
            str(t["points"]) if t.get("points") else None, t.get("link") or None)
        if created:
            new.append(t["title"])
    rt.memory.set("dashboard_synced_at", time.time())
    rt.memory.set("dashboard_stats", result.get("stats"))
    rt.memory.set("dashboard_text", text[:6000])
    return {"new": new, "stats": result.get("stats"), "count": len(result["tasks"])}


def _task_lines(rt: Any, include_done: bool = False) -> str:
    tasks = rt.memory.tasks(include_done)
    if not tasks:
        return "No tasks on file."
    return "\n".join(t.line() for t in tasks)


@tool("dashboard_tasks", "Get GSA tasks from the ambassador dashboard plus the user's own tasks. "
      "Set refresh=true to re-read the dashboard now.",
      params={"refresh": "Re-read the dashboard instead of using the cached copy"}, group="dashboard")
async def dashboard_tasks(rt: Any, refresh: bool = False) -> str:
    synced = rt.memory.get("dashboard_synced_at", 0)
    stale = time.time() - synced > rt.cfg.dashboard.refresh_minutes * 60
    note = ""
    if refresh or stale:
        try:
            res = await sync_dashboard(rt)
            note = f"Dashboard read just now: {res['count']} item(s), {len(res['new'])} new."
            if res["new"]:
                note += " New: " + "; ".join(res["new"])
        except Exception as e:  # noqa: BLE001
            age = f"{(time.time() - synced) / 3600:.1f}h old" if synced else "never synced"
            note = f"Couldn't read the dashboard ({e}). Showing cached tasks ({age})."
    stats = rt.memory.get("dashboard_stats")
    return "\n".join(x for x in [note, f"Progress: {stats}" if stats else "", _task_lines(rt)] if x)


@tool("dashboard_page", "Return the raw text of the ambassador dashboard, for questions the task list "
      "doesn't answer (points, rank, announcements).", group="dashboard")
async def dashboard_page(rt: Any) -> str:
    text = rt.memory.get("dashboard_text")
    if not text:
        await sync_dashboard(rt)
        text = rt.memory.get("dashboard_text", "")
    return text or "Dashboard text is empty."


@tool("add_task", "Add a task to the user's own list.",
      params={"title": "What to do", "due": "When, in plain words (e.g. 'friday 5pm'), optional",
              "notes": "Extra details, optional"}, group="core")
async def add_task(rt: Any, title: str, due: str = "", notes: str = "") -> str:
    due_iso = None
    if due:
        dt = dateparser.parse(due, settings={"PREFER_DATES_FROM": "future"})
        due_iso = dt.strftime("%Y-%m-%d %H:%M") if dt else due
    tid, _ = rt.memory.upsert_task("local", task_key(title + str(time.time())), title, due_iso, notes=notes or None)
    return f"Added task #{tid}: {title}" + (f" (due {due_iso})" if due_iso else "")


@tool("list_tasks", "List all open tasks (dashboard and personal).",
      params={"include_done": "Include finished tasks"}, group="core")
async def list_tasks(rt: Any, include_done: bool = False) -> str:
    return _task_lines(rt, include_done)


@tool("complete_task", "Mark a task done, by number or by (part of) its title.",
      params={"task": "Task number like 12 or #12, or words from its title"}, group="core")
async def complete_task(rt: Any, task: str) -> str:
    tasks = rt.memory.tasks()
    ref = task.strip().lstrip("#")
    target = next((t for t in tasks if ref.isdigit() and t.id == int(ref)), None)
    if target is None:
        titles = {t.title.lower(): t for t in tasks}
        hit = [t for t in tasks if ref.lower() in t.title.lower()] or [
            titles[k] for k in difflib.get_close_matches(ref.lower(), list(titles), n=1, cutoff=0.4)]
        target = hit[0] if hit else None
    if target is None:
        return f"No open task matches '{task}'."
    rt.memory.set_task_status(target.id, "done")
    extra = " (marked done here; submit it on the dashboard too)" if target.source == "dashboard" else ""
    return f"Done: #{target.id} {target.title}{extra}"
