"""Local diary storage, independent of the graphical interface.

Existing note rows stay in ``entries``. Chat rooms add ``messages`` and
``room_state`` beside them. Opening an older database copies each note into
the timeline once and leaves the original columns in place.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from contextlib import closing
from pathlib import Path
import json
import os
import re
import sqlite3
import uuid


CHAT_SCHEMA = "3"
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)(?:\s+|[.:-]\s*)?(.*)$")


def default_database() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "ShipMBLang" / "notebook.sqlite3"


def one_line(text: str, limit: int = 80) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 1)] + "…"


def guess_status(text: str) -> str:
    """Map a saved journal or compiler note onto a room badge."""
    lowered = (text or "").lower()
    if "clarif" in lowered or "which declared" in lowered or lowered.startswith("which "):
        return "ask"
    if any(token in lowered for token in ("could not", "unsupported", "error:", "failed to")):
        return "err"
    if any(token in lowered for token in ("compiled", "finished", "output:")):
        return "ok"
    return "draft"


def journal_events(journal: str) -> list[tuple[str, str]]:
    """Split a legacy journal into timeline events when it has dated lines."""
    text = journal or ""
    if not text.strip():
        return []
    events: list[tuple[str, str]] = []
    plain: list[str] = []
    saw_stamp = False
    for line in text.splitlines():
        match = _STAMP.match(line.strip())
        if match and match.group(1):
            saw_stamp = True
            body = (match.group(2) or "").strip() or match.group(1)
            events.append((match.group(1), body))
        elif saw_stamp and events and line.strip():
            stamp, body = events[-1]
            events[-1] = (stamp, f"{body}\n{line}".strip())
        else:
            plain.append(line)
    if not saw_stamp:
        return [("", text.strip())]
    if any(line.strip() for line in plain):
        events.insert(0, ("", "\n".join(plain).strip()))
    return [item for item in events if item[1].strip()]


def _normalize_stamp(stamp: str, fallback: str) -> str:
    raw = (stamp or "").strip()
    if not raw:
        return fallback
    if len(raw) == 10:
        return f"{raw}T00:00:00"
    if len(raw) >= 16 and raw[10] == " ":
        return raw[:10] + "T" + raw[11:]
    return raw


class NotebookStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute("""CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, entry_date TEXT NOT NULL,
                journal TEXT NOT NULL, program TEXT NOT NULL, updated_at TEXT NOT NULL,
                document TEXT NOT NULL DEFAULT ''
            )""")
            columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(entries)")}
            if "document" not in columns:
                self.connection.execute("ALTER TABLE entries ADD COLUMN document TEXT NOT NULL DEFAULT ''")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS notebook_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, entry_id TEXT NOT NULL, role TEXT NOT NULL,
                kind TEXT NOT NULL, body TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, parent_id TEXT)""")
            self.connection.execute("CREATE INDEX IF NOT EXISTS messages_entry ON messages(entry_id, created_at)")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS room_state (
                entry_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft',
                preview TEXT NOT NULL DEFAULT '', unread INTEGER NOT NULL DEFAULT 0,
                last_activity TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0)""")
            if self._meta("schema_version") != CHAT_SCHEMA:
                self._migrate_entries_to_rooms()
                self._set_meta("schema_version", CHAT_SCHEMA)

    def _meta(self, key: str) -> str:
        row = self.connection.execute("SELECT value FROM notebook_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self.connection.execute("""INSERT INTO notebook_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, value))

    def now(self) -> str:
        return datetime.now().astimezone().isoformat()

    def get_pref(self, key: str, default: str = "") -> str:
        value = self._meta("pref." + key)
        return value if value else default

    def set_pref(self, key: str, value: str) -> None:
        with self.connection:
            self._set_meta("pref." + key, value)

    def _migrate_entries_to_rooms(self) -> None:
        rows = list(self.connection.execute("SELECT * FROM entries"))
        for row in rows:
            existing = self.connection.execute(
                "SELECT 1 FROM messages WHERE entry_id=? LIMIT 1", (row["id"],)).fetchone()
            if existing:
                continue
            updated = row["updated_at"] or self.now()
            program = row["program"] or ""
            if program.strip():
                self._insert_message(
                    entry_id=row["id"], role="user", kind="opening", body=program,
                    detail=row["document"] or "", created_at=updated, parent_id=None,
                    status="draft", mark_unread=False)
            for stamp, body in journal_events(row["journal"] or ""):
                self._insert_message(
                    entry_id=row["id"], role="bot", kind="journal", body=body, detail="",
                    created_at=_normalize_stamp(stamp, updated), parent_id=None,
                    status=guess_status(body), mark_unread=False)
            if program.strip() or (row["journal"] or "").strip():
                continue
            self._ensure_room(row["id"], status="draft", preview=one_line(row["title"] or ""),
                              last_activity=updated, mark_unread=False)

    def save(self, *, entry_id=None, title, entry_date, journal, program, document=None):
        date.fromisoformat(entry_date)
        if len(entry_date) != 10:
            raise ValueError("Use a date in YYYY-MM-DD format.")
        entry_id = entry_id or str(uuid.uuid4())
        stamp = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute("""INSERT INTO entries
                (id, title, entry_date, journal, program, updated_at, document)
                VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, ''))
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                entry_date=excluded.entry_date, journal=excluded.journal,
                program=excluded.program, updated_at=excluded.updated_at,
                document=CASE WHEN ? IS NULL THEN entries.document ELSE ? END""",
                (entry_id, title.strip() or "Untitled entry", entry_date, journal, program, stamp,
                 document, document, document))
            self._touch_draft(entry_id, program, stamp)
        return entry_id

    def _touch_draft(self, entry_id: str, program: str, stamp: str) -> None:
        preview = one_line(program)
        row = self.connection.execute("SELECT preview FROM room_state WHERE entry_id=?", (entry_id,)).fetchone()
        if row is None:
            self.connection.execute("""INSERT INTO room_state
                (entry_id, status, preview, unread, last_activity, pinned)
                VALUES (?, 'draft', ?, 0, ?, 0)""", (entry_id, preview, stamp))
            return
        if program.strip():
            self.connection.execute(
                "UPDATE room_state SET preview=?, last_activity=? WHERE entry_id=?",
                (preview, stamp, entry_id))
        else:
            self.connection.execute(
                "UPDATE room_state SET last_activity=? WHERE entry_id=?", (stamp, entry_id))

    def _ensure_room(self, entry_id, *, status, preview, last_activity, mark_unread) -> None:
        row = self.connection.execute("SELECT status, preview, unread, pinned FROM room_state WHERE entry_id=?", (entry_id,)).fetchone()
        unread = 1 if mark_unread else 0
        if row is None:
            self.connection.execute("""INSERT INTO room_state
                (entry_id, status, preview, unread, last_activity, pinned)
                VALUES (?, ?, ?, ?, ?, 0)""", (entry_id, status or "draft", preview or "", unread, last_activity))
            return
        next_status = status or row["status"]
        next_preview = preview if preview else row["preview"]
        next_unread = 1 if mark_unread else row["unread"]
        self.connection.execute("""UPDATE room_state SET status=?, preview=?, unread=?, last_activity=?
            WHERE entry_id=?""", (next_status, next_preview, next_unread, last_activity, entry_id))

    def _insert_message(self, *, entry_id, role, kind, body, detail, created_at, parent_id, status, mark_unread) -> str:
        message_id = str(uuid.uuid4())
        detail_text = detail if isinstance(detail, str) else json.dumps(detail or {}, ensure_ascii=False)
        self.connection.execute("""INSERT INTO messages
            (id, entry_id, role, kind, body, detail, created_at, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, entry_id, role, kind, body, detail_text, created_at, parent_id))
        self._ensure_room(entry_id, status=status, preview=one_line(body),
                          last_activity=created_at, mark_unread=mark_unread)
        return message_id

    def add_message(self, *, entry_id, role, kind="message", body="", detail="", parent_id=None, created_at=None, status=None, mark_unread=None):
        if self.get(entry_id) is None:
            raise ValueError("Choose a chat before adding a message.")
        if parent_id == "":
            parent_id = None
        created_at = created_at or datetime.now(timezone.utc).isoformat()
        if status is None and role == "bot":
            status = _status_from_detail(detail)
        if mark_unread is None:
            mark_unread = role == "bot"
        with self.connection:
            message_id = self._insert_message(
                entry_id=entry_id, role=role, kind=kind, body=body, detail=detail,
                created_at=created_at, parent_id=parent_id, status=status, mark_unread=mark_unread)
        return self.message(message_id)

    def message(self, message_id):
        row = self.connection.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return _public_message(row) if row else None

    def messages(self, entry_id):
        rows = self.connection.execute("""SELECT * FROM messages WHERE entry_id=?
            ORDER BY created_at, rowid""", (entry_id,))
        return [_public_message(row) for row in rows]

    def mark_read(self, entry_id):
        with self.connection:
            self.connection.execute("UPDATE room_state SET unread=0 WHERE entry_id=?", (entry_id,))

    def set_pinned(self, entry_id, pinned: bool):
        if self.get(entry_id) is None:
            raise ValueError("Choose a chat before pinning it.")
        with self.connection:
            row = self.connection.execute("SELECT 1 FROM room_state WHERE entry_id=?", (entry_id,)).fetchone()
            if row is None:
                self._ensure_room(entry_id, status="draft", preview="", last_activity=self.now(), mark_unread=False)
            self.connection.execute("UPDATE room_state SET pinned=? WHERE entry_id=?", (1 if pinned else 0, entry_id))

    def get(self, entry_id):
        row = self.connection.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def list(self, query=""):
        rows = self.connection.execute("""SELECT e.id, e.title, e.entry_date, e.updated_at,
            COALESCE(r.status, 'draft') AS status,
            COALESCE(NULLIF(r.preview, ''), '') AS preview,
            COALESCE(NULLIF(r.last_activity, ''), e.updated_at) AS last_activity,
            COALESCE(r.unread, 0) AS unread,
            COALESCE(r.pinned, 0) AS pinned
            FROM entries e
            LEFT JOIN room_state r ON r.entry_id = e.id
            WHERE instr(lower(e.title || char(10) || e.journal || char(10) || e.program || char(10) ||
                IFNULL((SELECT group_concat(body, char(10)) FROM messages m WHERE m.entry_id = e.id), '')),
                lower(?)) > 0
            ORDER BY COALESCE(r.pinned, 0) DESC,
                COALESCE(NULLIF(r.last_activity, ''), e.updated_at) DESC,
                e.entry_date DESC, e.updated_at DESC""", (query,))
        return [dict(row) for row in rows]

    def delete(self, entry_id):
        with self.connection:
            self.connection.execute("DELETE FROM messages WHERE entry_id=?", (entry_id,))
            self.connection.execute("DELETE FROM room_state WHERE entry_id=?", (entry_id,))
            self.connection.execute("DELETE FROM entries WHERE id=?", (entry_id,))

    def backup(self, destination):
        target = Path(destination).expanduser().resolve()
        if target == self.path:
            raise ValueError("Choose a different file for the backup.")
        with closing(sqlite3.connect(target)) as backup:
            self.connection.backup(backup)

    def close(self):
        self.connection.close()


def _status_from_detail(detail) -> str:
    payload = detail
    if isinstance(detail, str):
        try:
            payload = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        return "ok"
    status = str(payload.get("status") or "")
    if status == "compiled":
        return "ok"
    if status == "needs_clarification":
        return "ask"
    if status or payload.get("diagnostics"):
        return "err"
    return "ok"


def _public_message(row) -> dict:
    item = dict(row)
    raw = item.get("detail") or ""
    if isinstance(raw, str) and raw:
        try:
            item["detail"] = json.loads(raw)
        except json.JSONDecodeError:
            item["detail"] = {"text": raw}
    elif not raw:
        item["detail"] = {}
    return item
