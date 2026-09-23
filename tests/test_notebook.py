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
            for window in list(reversed(self.app.windows)):
                window.dispose()
            self.store.close()
            self.directory.cleanup()

    def wait_until(self, predicate, timeout=3):
        import time
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_autosave_and_reopen(self):
        app = self.app
        app.program.insert("1.0", 'Present "Today’s idea".')
        self.root.update()
        self.assertTrue(app.dirty)
        self.wait_until(lambda: not app.dirty)
        entry_id = app.entry_id
        self.assertEqual(self.store.get(entry_id)["program"], 'Present "Today’s idea".')
        self.assertEqual(self.store.list("idea")[0]["id"], entry_id)
        self.assertIs(app.new_note(self.store.get(entry_id)), app)

    def test_run_entire_note_and_toggle_terminal_without_losing_output(self):
        app = self.app
        app.program.insert("1.0", "Show 5. Show 9.")
        self.root.update()
        app.program.tag_add("sel", "1.0", "1.7")
        self.assertFalse(app.terminal_visible)
        with patch("shipmblang.notebook.execute_program", return_value=(0, {"runtime": {"stdout": "5\n9\n"}})) as execute:
            app.run_button.invoke()
            self.wait_until(lambda: not app.busy)
        execute.assert_called_once_with("Show 5. Show 9.", "run")
        self.assertFalse(app.busy)
        self.assertTrue(app.terminal_visible)
        app.terminal_button.invoke()
        self.assertFalse(app.terminal_visible)
        app.terminal_button.invoke()
        self.assertTrue(app.terminal_visible)
        self.assertEqual(app.output.get("1.0", "end-1c"), "5\n9\n")

    def test_failed_save_keeps_note_open(self):
        import sqlite3
        self.app.program.insert("1.0", "Show 7.")
        self.root.update()
        with patch.object(self.store, "save", side_effect=sqlite3.OperationalError("read only")), patch("tkinter.messagebox.showerror"):
            self.app.close()
        self.assertTrue(self.app.dirty)
        self.assertEqual(self.app.status.get(), "Not saved")
        self.assertTrue(self.root.winfo_exists())

    def test_two_buttons_and_independent_notes(self):
        buttons = [w.cget("text") for w in self.app.footer.winfo_children() if w.winfo_class() == "Button"]
        self.assertEqual(buttons, ["Run", "Terminal"])
        second = self.app.new_note()
        second.root.withdraw()
        self.app.program.insert("1.0", "Show 1.")
        second.program.insert("1.0", "Show 2.")
        self.root.update()
        self.app.save()
        second.save()
        self.assertNotEqual(self.app.entry_id, second.entry_id)
        self.assertEqual(self.store.get(second.entry_id)["program"], "Show 2.")

    def test_preserves_old_journal_and_does_not_execute_it(self):
        entry_id = self.store.save(title="Old diary", entry_date="2026-09-23",
                                  journal="This diary is private prose.", program="Show 3.")
        note = self.app.new_note(self.store.get(entry_id))
        note.root.withdraw()
        self.assertEqual(note.text(), "Show 3.")
        note.program.delete("1.0", "end")
        self.root.update()
        note.save()
        self.assertEqual(self.store.get(entry_id)["journal"], "This diary is private prose.")
        self.assertEqual(self.store.get(entry_id)["program"], "")

    def test_delete_cancels_pending_autosave(self):
        self.app.program.insert("1.0", "Show 8.")
        self.root.update()
        self.app.save()
        self.app.program.insert("end", " Show 9.")
        self.root.update()
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.app.delete_note()
        self.root.update()
        self.assertIsNone(self.app.save_id)
        self.assertFalse(self.app.dirty)
        self.assertEqual(self.store.list(), [])

    def test_result_after_edit_is_labeled_and_does_not_reopen_hidden_terminal(self):
        self.app.program.insert("1.0", "Show 9.")
        self.root.update()
        self.app.results.put(("Show 5.", "5\n"))
        self.wait_until(lambda: "before your latest edit" in self.app.output.get("1.0", "end-1c"))
        self.assertFalse(self.app.terminal_visible)
