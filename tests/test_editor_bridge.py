"""Persistence checks for the Ratatui editor's JSON database bridge."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from shipmblang.editor_bridge import handle
from shipmblang.notebook_store import NotebookStore


class EditorBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = NotebookStore(Path(self.directory.name) / "editor.sqlite3")
        self.addCleanup(self.store.close)

    def test_save_load_keeps_ordered_image_document_and_english(self):
        document = {"version": 2, "images": [
            {"id": "4", "path": "first.png", "caption": "first"},
            {"id": "9", "path": "second.png", "caption": "second"},
        ]}
        saved = handle(self.store, {
            "action": "save", "title": "Image note", "entry_date": date.today().isoformat(),
            "program": "Read [[image:4]], then [[image:9]].", "document": document,
        })

        loaded = handle(self.store, {"action": "get", "id": saved["entry"]["id"]})["entry"]
        self.assertEqual(loaded["program"], "Read [[image:4]], then [[image:9]].")
        self.assertEqual(json.loads(loaded["document"]), document)

    def test_unknown_actions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown editor database action"):
            handle(self.store, {"action": "run"})


if __name__ == "__main__":
    unittest.main()
