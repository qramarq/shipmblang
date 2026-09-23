"""Local diary storage, independent of the graphical interface."""
from __future__ import annotations

from datetime import date, datetime, timezone
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import uuid


def default_database() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "ShipMBLang" / "notebook.sqlite3"


class NotebookStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute("""CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, entry_date TEXT NOT NULL,
                journal TEXT NOT NULL, program TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")

    def save(self, *, entry_id=None, title, entry_date, journal, program):
        date.fromisoformat(entry_date)
        if len(entry_date) != 10:
            raise ValueError("Use a date in YYYY-MM-DD format.")
        entry_id = entry_id or str(uuid.uuid4())
        stamp = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute("""INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                entry_date=excluded.entry_date, journal=excluded.journal,
                program=excluded.program, updated_at=excluded.updated_at""",
                (entry_id, title.strip() or "Untitled entry", entry_date, journal, program, stamp))
        return entry_id

    def get(self, entry_id):
        row = self.connection.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def list(self, query=""):
        rows = self.connection.execute("""SELECT id, title, entry_date FROM entries
            WHERE instr(lower(title || char(10) || journal || char(10) || program), lower(?)) > 0
            ORDER BY entry_date DESC, updated_at DESC""", (query,))
        return [dict(row) for row in rows]

    def delete(self, entry_id):
        with self.connection:
            self.connection.execute("DELETE FROM entries WHERE id=?", (entry_id,))

    def backup(self, destination):
        target = Path(destination).expanduser().resolve()
        if target == self.path:
            raise ValueError("Choose a different file for the backup.")
        with closing(sqlite3.connect(target)) as backup:
            self.connection.backup(backup)

    def close(self):
        self.connection.close()
