"""Exercise the same CLI used by external text editors and clipboard pipes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TextAppTests(unittest.TestCase):
    def invoke(self, *args, source=None):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "shipmblang", *args,
             "--memory", "off", "--no-english-model"],
            input=source, capture_output=True, encoding="utf-8",
            cwd=Path(__file__).resolve().parents[1],
        )

    def test_clipboard_prose_and_slang(self):
        result = self.invoke("run", "--file", "-", "--format", "text",
                             source="Pls show me the total of 2 and 3.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "5\n")

    def test_unicode_quoted_data_preserved(self):
        source = 'Present "café: add install aggregate".'
        result = self.invoke("run", "--file", "-", source=source)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source"], source)
        self.assertEqual(payload["runtime"]["stdout"], "café: add install aggregate\n")

    def test_notepad_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "my notes.txt"
            path.write_text("Present the sum of 2 and 3.", encoding="utf-8")
            result = self.invoke("run", "--file", str(path), "--format", "text")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "5\n")

    def test_failure_still_shows_diagnostics(self):
        result = self.invoke("run", "--file", "-", "--format", "text",
                             source="Present it.")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("runtime", json.loads(result.stdout))

    def test_compile_from_stdin(self):
        result = self.invoke("compile", "--file", "-", "--format", "json",
                             source="Show 5.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "compiled")

    def test_conflicting_inputs_rejected(self):
        result = self.invoke("run", "Show 9.", "--file", "-", source="Show 5.")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not both", result.stderr)
