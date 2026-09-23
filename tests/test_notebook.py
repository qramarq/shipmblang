"""Persistence and real compiler checks for the desktop diary."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shipmblang.notebook import execute_program
from shipmblang.notebook_store import NotebookStore


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "notes.sqlite3"
        self.store = NotebookStore(self.path)
        self.addCleanup(self.store.close)

    def save(self, **options):
        values = dict(title="A day’s thoughts", entry_date="2026-09-23",
                      journal="Private diary: don't run this.", program='Present "café".')
        values.update(options)
        return self.store.save(**values)

    def test_save_update_reopen_and_literal_search(self):
        entry_id = self.save()
        self.save(entry_id=entry_id, title="Revised 100%", program="Show 8.")
        reopened = NotebookStore(self.path)
        try:
            self.assertEqual(reopened.get(entry_id)["program"], "Show 8.")
            self.assertEqual(len(reopened.list()), 1)
            self.assertEqual(reopened.list("100%")[0]["id"], entry_id)
            self.assertEqual(reopened.list("private")[0]["id"], entry_id)
            self.assertEqual(reopened.list("' OR 1=1 --"), [])
        finally:
            reopened.close()

    def test_bad_date_does_not_change_saved_entry(self):
        entry_id = self.save()
        with self.assertRaises(ValueError):
            self.save(entry_id=entry_id, entry_date="2026-02-30")
        self.assertEqual(self.store.get(entry_id)["entry_date"], "2026-09-23")

    def test_backup_and_delete(self):
        entry_id = self.save()
        backup_path = Path(self.directory.name) / "backup.sqlite3"
        self.store.backup(backup_path)
        self.store.delete(entry_id)
        self.assertEqual(self.store.list(), [])
        backup = NotebookStore(backup_path)
        try:
            self.assertEqual(backup.get(entry_id)["title"], "A day’s thoughts")
        finally:
            backup.close()
        with self.assertRaises(ValueError):
            self.store.backup(self.path)

    def test_actual_compile_and_run(self):
        source = 'Pls show me the total of 2 and 3. Present "café".'
        code, compiled = execute_program(source, "compile")
        self.assertEqual(code, 0)
        self.assertIsNotNone(compiled["target_code"])
        self.assertNotIn("runtime", compiled)
        code, result = execute_program(source, "run")
        self.assertEqual(code, 0)
        self.assertEqual(result["runtime"]["stdout"], "5\ncafé\n")

    def test_unknown_prose_does_not_run(self):
        code, result = execute_program("Present it.", "run")
        self.assertNotEqual(code, 0)
        self.assertNotIn("runtime", result)

    def test_execution_is_bounded_and_offline(self):
        import subprocess
        with patch("shipmblang.notebook.subprocess.run", side_effect=subprocess.TimeoutExpired("compiler", 1)) as runner:
            with self.assertRaises(subprocess.TimeoutExpired):
                execute_program("Show 5.", "run", timeout=1)
        args, options = runner.call_args
        self.assertIn("--no-english-model", args[0])
        self.assertEqual(options["timeout"], 1)
        self.assertIn("off", args[0])
        with self.assertRaises(ValueError):
            execute_program("", "run")


class NotebookInterfaceTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from shipmblang.notebook import NotebookApp
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Desktop display unavailable: {error}")
        self.root.withdraw()
        self.directory = tempfile.TemporaryDirectory()
        self.store = NotebookStore(Path(self.directory.name) / "ui.sqlite3")
        self.app = NotebookApp(self.root, self.store)
        self.root.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.root.after_cancel(self.app.poll_id)
            self.root.destroy()
            self.store.close()
            self.directory.cleanup()

    def test_save_switch_search_and_reopen(self):
        app = self.app
        app.title.set("Today")
        app.journal.insert("1.0", "My diary isn't a program.")
        app.example()
        self.root.update()
        self.assertTrue(app.dirty)
        self.assertTrue(app.save())
        entry_id = app.entry_id
        app.new_entry()
        self.root.update()
        self.assertFalse(app.dirty)
        self.assertEqual(app.journal.get("1.0", "end-1c"), "")
        app.entries.selection_set(entry_id)
        self.root.update()
        self.assertEqual(app.title.get(), "Today")
        self.assertIn("isn't a program", app.journal.get("1.0", "end-1c"))
        app.search.set("not found")
        self.root.update()
        self.assertEqual(app.entries.get_children(), ())

    def test_only_program_selection_sent_to_compiler(self):
        import time
        app = self.app
        app.journal.insert("1.0", "This private diary must never be compiled.")
        app.program.insert("1.0", "Show 5. Show 9.")
        self.root.update()
        app.program.tag_add("sel", "1.0", "1.7")
        with patch("shipmblang.notebook.execute_program", return_value=(0, {"runtime": {"stdout": "5\n"}})) as execute:
            app.execute("run")
            deadline = time.monotonic() + 3
            while app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
        execute.assert_called_once_with("Show 5.", "run")
        self.assertFalse(app.busy)
        self.assertEqual(app.output.get("1.0", "end-1c"), "5\n")

    def test_cancel_preserves_dirty_entry(self):
        self.app.title.set("Unsaved thought")
        with patch("tkinter.messagebox.askyesnocancel", return_value=None):
            self.app.new_entry()
        self.assertEqual(self.app.title.get(), "Unsaved thought")
        self.assertTrue(self.app.dirty)
