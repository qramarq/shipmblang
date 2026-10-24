"""Non-destructive migration of diary notes into chat rooms."""
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shipmblang.editor_bridge import handle
from shipmblang.notebook_store import NotebookStore, journal_events


class LegacyMigrationTests(unittest.TestCase):
    def test_pre_chat_database_keeps_text_and_gains_a_timeline(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "legacy.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("""CREATE TABLE entries (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, entry_date TEXT NOT NULL,
            journal TEXT NOT NULL, program TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        connection.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
            ("note-1", "Morning", "2026-09-23",
             "2026-09-23 09:00 Walked the dog\n\n2026-09-23 15:00 Compiled the sum",
             'Present "café".', "2026-09-23T15:00:00+00:00"))
        connection.commit()
        connection.close()

        store = NotebookStore(path)
        self.addCleanup(store.close)
        entry = store.get("note-1")
        self.assertEqual(entry["program"], 'Present "café".')
        self.assertIn("Walked the dog", entry["journal"])
        self.assertEqual(entry["title"], "Morning")
        self.assertEqual(entry["document"], "")
        messages = store.messages("note-1")
        bodies = [message["body"] for message in messages]
        self.assertIn('Present "café".', bodies)
        self.assertTrue(any("Walked the dog" in body for body in bodies))
        self.assertTrue(any("Compiled the sum" in body for body in bodies))
        self.assertEqual(store.list()[0]["id"], "note-1")
        self.assertIn(store.list()[0]["status"], {"ok", "draft", "ask", "err"})
        count = len(messages)
        store.close()

        again = NotebookStore(path)
        self.addCleanup(again.close)
        self.assertEqual(len(again.messages("note-1")), count)
        self.assertEqual(again.get("note-1")["program"], 'Present "café".')
        self.assertEqual(again.get("note-1")["journal"].count("Walked the dog"), 1)

    def test_unstamped_journal_is_one_history_message(self):
        self.assertEqual(journal_events("Private diary: don't run this."), [("", "Private diary: don't run this.")])
        self.assertEqual(journal_events("   "), [])

    def test_new_saves_do_not_invent_timeline_copies(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = NotebookStore(Path(directory.name) / "notes.sqlite3")
        self.addCleanup(store.close)
        entry_id = store.save(title="Later", entry_date="2026-10-01", journal="kept aside", program="Show 8.")
        self.assertEqual(store.messages(entry_id), [])
        self.assertEqual(store.get(entry_id)["journal"], "kept aside")
        self.assertEqual(store.get(entry_id)["program"], "Show 8.")
        rooms = store.list()
        self.assertEqual(rooms[0]["preview"], "Show 8.")
        self.assertEqual(rooms[0]["status"], "draft")

    def test_messages_search_backup_and_delete(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "notes.sqlite3"
        store = NotebookStore(path)
        self.addCleanup(store.close)
        entry_id = store.save(title="Room", entry_date=date.today().isoformat(), journal="", program="Show 1.")
        saved = handle(store, {
            "action": "append", "id": entry_id, "role": "bot", "kind": "reply",
            "body": "unique-token-zebra", "detail": {"status": "compiled", "stdout": "1\n"},
        })
        self.assertEqual(saved["message"]["detail"]["status"], "compiled")
        self.assertEqual(store.list("unique-token-zebra")[0]["id"], entry_id)
        self.assertEqual(store.list()[0]["status"], "ok")
        self.assertEqual(store.list("' OR 1=1 --"), [])
        backup_path = Path(directory.name) / "backup.sqlite3"
        store.backup(backup_path)
        store.delete(entry_id)
        self.assertEqual(store.messages(entry_id), [])
        self.assertIsNone(store.get(entry_id))
        backup = NotebookStore(backup_path)
        self.addCleanup(backup.close)
        self.assertEqual(backup.get(entry_id)["program"], "Show 1.")
        self.assertEqual(backup.messages(entry_id)[0]["body"], "unique-token-zebra")


if __name__ == "__main__":
    unittest.main()
