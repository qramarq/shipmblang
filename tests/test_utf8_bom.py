"""Notepad and PowerShell UTF-8 BOM must not become source wording."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shipmblang import run_direct_program


@unittest.skipIf(sys.version_info < (3, 11), "Direct compiler requires Python 3.11+")
class Utf8BomTests(unittest.TestCase):
    def test_leading_bom_compiles_and_prints_sum(self):
        result = run_direct_program("\ufeffShow the sum of 2 and 3.", memory=False, model_provider=None)
        self.assertEqual(result["status"], "compiled", result)
        self.assertEqual(result["runtime"]["stdout"], "5\n")

    def test_bom_inside_a_clause_is_not_unconsumed_wording(self):
        result = run_direct_program("Show the\ufeff sum of 2 and 3.", memory=False, model_provider=None)
        self.assertEqual(result["status"], "compiled", result)
        self.assertEqual(result["runtime"]["stdout"], "5\n")
        self.assertNotIn("\ufeff", [token["text"] for token in result["tokens"]])

    def test_cli_file_reader_drops_bom_and_runs(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.txt"
            path.write_bytes(b"\xef\xbb\xbf" + b"Show the sum of 2 and 3.")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(root)
            text = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "shipmblang", "run",
                 "--file", str(path), "--no-english-model", "--memory", "off", "--format", "text"],
                capture_output=True, encoding="utf-8", cwd=root, env=env,
            )
            documented = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "shipmblang", "run",
                 "--file", str(path), "--no-english-model", "--memory", "off", "--format", "json"],
                capture_output=True, encoding="utf-8", cwd=root, env=env,
            )
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertEqual(text.stdout, "5\n")
        self.assertEqual(documented.returncode, 0, documented.stderr)
        payload = json.loads(documented.stdout)
        self.assertEqual(payload["source"], "Show the sum of 2 and 3.")
        self.assertEqual(payload["status"], "compiled")
        self.assertEqual(payload["runtime"]["stdout"], "5\n")


if __name__ == "__main__":
    unittest.main()
