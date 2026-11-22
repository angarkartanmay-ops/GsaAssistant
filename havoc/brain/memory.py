"""SQLite store: conversation, long-term facts, tasks, seen items, reminders, kv."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT, channel TEXT);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY, ts REAL, text TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, source TEXT, ext_id TEXT, title TEXT, due TEXT,
  status TEXT DEFAULT 'open', points TEXT, link TEXT, notes TEXT,
  created REAL, updated REAL, UNIQUE(source, ext_id));
CREATE TABLE IF NOT EXISTS seen(
  source TEXT, ext_id TEXT, ts REAL, PRIMARY KEY(source, ext_id));
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY, due_ts REAL, text TEXT, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class Task:
    id: int
    source: str
    ext_id: str
    title: str
    due: Optional[str]
    status: str
    points: Optional[str]
    link: Optional[str]
    notes: Optional[str]

    def line(self) -> str:
        bits = [f"#{self.id} [{self.source}] {self.title}"]
        if self.due:
            bits.append(f"due {self.due}")
        if self.points:
            bits.append(f"{self.points} pts")
        if self.status != "open":
            bits.append(self.status)
        return " | ".join(bits)


class Memory:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # conversation
    def add_message(self, role: str, content: str, channel: str = "text") -> None:
        self._exec("INSERT INTO messages(ts, role, content, channel) VALUES(?,?,?,?)",
                   (time.time(), role, content, channel))

    def recent_messages(self, limit: int = 16) -> list[dict]:
        rows = self._all("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,))
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def history(self, limit: int = 40) -> list[dict]:
        """Conversation across every device and channel, oldest first (the shared brain's log)."""
        rows = self._all("SELECT ts, role, content, channel FROM messages ORDER BY id DESC LIMIT ?", (limit,))
        return [{"ts": r["ts"], "role": r["role"], "content": r["content"], "channel": r["channel"]}
                for r in reversed(rows)]

    def clear_history(self) -> None:
        self._exec("DELETE FROM messages")

    # facts
    def remember(self, text: str) -> None:
        self._exec("INSERT OR IGNORE INTO facts(ts, text) VALUES(?,?)", (time.time(), text.strip()))

    def forget(self, query: str) -> int:
        cur = self._exec("DELETE FROM facts WHERE text LIKE ?", (f"%{query}%",))
        return cur.rowcount

    def facts(self, limit: int = 40) -> list[str]:
        return [r["text"] for r in self._all("SELECT text FROM facts ORDER BY id DESC LIMIT ?", (limit,))]

    # tasks
    def upsert_task(self, source: str, ext_id: str, title: str, due: str | None = None,
                    status: str = "open", points: str | None = None, link: str | None = None,
                    notes: str | None = None) -> tuple[int, bool]:
        """Insert or update a task. Returns (id, created)."""
        now = time.time()
        existing = self._all("SELECT id FROM tasks WHERE source=? AND ext_id=?", (source, ext_id))
        if existing:
            tid = existing[0]["id"]
            self._exec("UPDATE tasks SET title=?, due=?, status=?, points=?, link=?, "
                       "notes=COALESCE(?, notes), updated=? WHERE id=?",
                       (title, due, status, points, link, notes, now, tid))
            return tid, False
        cur = self._exec("INSERT INTO tasks(source, ext_id, title, due, status, points, link, notes,"
                         " created, updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (source, ext_id, title, due, status, points, link, notes, now, now))
        return int(cur.lastrowid), True

    def tasks(self, include_done: bool = False) -> list[Task]:
        sql = "SELECT * FROM tasks"
        if not include_done:
            sql += " WHERE status NOT IN ('done', 'completed', 'submitted')"
        sql += " ORDER BY (due IS NULL), due, id"
        return [Task(r["id"], r["source"], r["ext_id"], r["title"], r["due"], r["status"],
                     r["points"], r["link"], r["notes"]) for r in self._all(sql)]

    def set_task_status(self, task_id: int, status: str) -> bool:
        return self._exec("UPDATE tasks SET status=?, updated=? WHERE id=?",
                          (status, time.time(), task_id)).rowcount > 0

    # seen items (dedupe for alerts)
    def mark_seen(self, source: str, ext_id: str) -> bool:
        """Returns True if this is the first time we see it."""
        cur = self._exec("INSERT OR IGNORE INTO seen(source, ext_id, ts) VALUES(?,?,?)",
                         (source, str(ext_id), time.time()))
        return cur.rowcount > 0

    # reminders
    def add_reminder(self, due_ts: float, text: str) -> int:
        return int(self._exec("INSERT INTO reminders(due_ts, text) VALUES(?,?)", (due_ts, text)).lastrowid)

    def due_reminders(self, now: float | None = None) -> list[tuple[int, float, str]]:
        now = now or time.time()
        rows = self._all("SELECT id, due_ts, text FROM reminders WHERE done=0 AND due_ts<=?", (now,))
        return [(r["id"], r["due_ts"], r["text"]) for r in rows]

    def upcoming_reminders(self, within_s: float = 86400) -> list[tuple[int, float, str]]:
        now = time.time()
        rows = self._all("SELECT id, due_ts, text FROM reminders WHERE done=0 AND due_ts<=? ORDER BY due_ts",
                         (now + within_s,))
        return [(r["id"], r["due_ts"], r["text"]) for r in rows]

    def finish_reminder(self, rid: int) -> None:
        self._exec("UPDATE reminders SET done=1 WHERE id=?", (rid,))

    # kv
    def get(self, key: str, default: Any = None) -> Any:
        rows = self._all("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key: str, value: Any) -> None:
        self._exec("INSERT OR REPLACE INTO kv(key, value) VALUES(?,?)", (key, json.dumps(value)))
