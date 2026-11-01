"""Plain run output: program stdout, and file:line:col diagnostics on failure.

Default JSON output stays in place for existing consumers. Positions are
Unicode code points, so a column after "é" is not a UTF-8 byte index.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shipmblang.pipelines import _offset_line_column, _plain_line


ROOT = Path(__file__).resolve().parents[1]


def _run(*args, source=None, path=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["SHIPMB_MEMORY"] = "off"
    env["SHIPMB_MODEL_PROVIDER"] = "none"
    command = [sys.executable, "-X", "utf8", "-m", "shipmblang", *args]
    if path is not None:
        command.extend(["--file", str(path)])
    return subprocess.run(
        command,
        input=None if source is None else source.encode("utf-8"),
        capture_output=True,
        cwd=ROOT,
        env=env,
    )


@unittest.skipIf(sys.version_info < (3, 11), "Direct compiler requires Python 3.11+")
class PlainOutputTests(unittest.TestCase):
    def write(self, directory, name, source):
        path = Path(directory) / name
        path.write_bytes(source.encode("utf-8"))
        return path

    def test_plain_run_prints_program_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "hello.shipmb", "Show 27.\n")
            result = _run(
                "run", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model", "--plain",
                path=path,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"27\n")
        self.assertEqual(result.stderr, b"")

    def test_compile_run_plain_prints_the_same_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "hello.shipmb", "Show 27.\n")
            result = _run(
                "compile", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model", "--run", "--plain",
                "--format", "json",
                path=path,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"27\n")
        self.assertNotIn(b"syntax_tree", result.stdout)

    def test_default_run_is_still_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "hello.shipmb", "Show 27.\n")
            result = _run(
                "run", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model",
                path=path,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(payload["source"], "Show 27.\n")
        self.assertIn("bytecode", payload["target_code"])
        self.assertIn("tokens", payload)
        self.assertIn("syntax_tree", payload)
        self.assertIn("diagnostics", payload)
        self.assertEqual(payload["runtime"]["stdout"], "27\n")

    def test_compile_diagnostic_is_positioned_on_stderr(self):
        source = "Hello world.\n"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "broken.shipmb", source)
            result = _run(
                "run", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model", "--plain",
                path=path,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        stderr = result.stderr.decode("utf-8")
        self.assertIn(f"{path}:1:1:", stderr)
        self.assertIn("not implemented by the general computation grammar", stderr)
        self.assertNotIn("syntax_tree", stderr)
        self.assertNotIn("{", result.stdout.decode("utf-8"))

    def test_clarification_uses_the_same_position_style(self):
        source = 'Show "café" and then show the total.'
        start = source.index("total")
        self.assertNotEqual(len(source[:start].encode("utf-8")), start)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "clarify.shipmb", source)
            result = _run(
                "run", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model", "--plain",
                path=path,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        stderr = result.stderr.decode("utf-8")
        line, column = _offset_line_column(source, {"start": start})
        self.assertEqual((line, column), (1, start + 1))
        self.assertIn(f"{path}:{line}:{column}:", stderr)
        byte_column = len(source[:start].encode("utf-8")) + 1
        self.assertNotEqual(byte_column, column)
        self.assertNotIn(f"{path}:{line}:{byte_column}:", stderr)
        self.assertIn("question:", stderr)
        self.assertIn("not a declared value", stderr)

    def test_runtime_failure_exits_nonzero_with_a_position(self):
        source = "Let total be a mutable integer with value 1.\r\nShow total divided by 0."
        start = source.index("total divided")
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "divide.shipmb", source)
            result = _run(
                "run", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model", "--plain",
                path=path,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        stderr = result.stderr.decode("utf-8")
        line, column = _offset_line_column(source, {"start": start})
        self.assertEqual((line, column), (2, 6))
        self.assertIn(f"{path}:{line}:{column}:", stderr)
        self.assertIn("Division by zero", stderr)
        self.assertNotIn("target_code", stderr)

    def test_utf8_stdout_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "cafe.shipmb", 'Show "café".\n')
            result = _run(
                "run", "--pipeline", "direct", "--profile", "general",
                "--memory", "off", "--no-english-model", "--plain",
                path=path,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "café\n".encode("utf-8"))

    def test_stdin_label_and_bare_file_shorthand(self):
        piped = _run(
            "run", "--pipeline", "direct", "--profile", "general",
            "--memory", "off", "--no-english-model", "--plain", "--file", "-",
            source="Hello world.\n",
        )
        self.assertEqual(piped.returncode, 1)
        self.assertIn("<stdin>:1:1:", piped.stderr.decode("utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "hello.shipmb", "Show 27.\n")
            bare = _run(str(path), "--plain")
        self.assertEqual(bare.returncode, 0, bare.stderr)
        self.assertEqual(bare.stdout, b"27\n")

    def test_plain_requires_a_direct_run(self):
        compile_only = _run("compile", "--plain", "--no-english-model")
        self.assertEqual(compile_only.returncode, 2)
        self.assertIn("--plain requires run or compile --run.", compile_only.stderr.decode("utf-8"))
        legacy = _run("run", "--pipeline", "legacy", "--plain", "--memory", "off")
        self.assertEqual(legacy.returncode, 2)
        self.assertIn("--plain requires --pipeline direct.", legacy.stderr.decode("utf-8"))

    def test_help_mentions_plain(self):
        result = _run("run", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--plain", result.stdout.decode("utf-8"))
        self.assertIn("file:line:col: message", result.stdout.decode("utf-8"))


class PlainPositionTests(unittest.TestCase):
    def test_windows_path_is_preserved(self):
        path = r"C:\notes\hello.shipmb"
        self.assertEqual(
            _plain_line(path, "Hello world.", {"start": 0, "end": 5}, "error SMBG100: nope"),
            r"C:\notes\hello.shipmb:1:1: error SMBG100: nope",
        )

    def test_crlf_and_code_points_do_not_shift_the_next_line(self):
        source = 'Show "café".\r\nHello'
        start = source.index("Hello")
        self.assertEqual(_offset_line_column(source, {"start": start}), (2, 1))
        self.assertGreater(len(source[:start].encode("utf-8")), start)

    def test_missing_span_is_the_first_character(self):
        self.assertEqual(_offset_line_column("abc", None), (1, 1))
        self.assertEqual(_offset_line_column("abc", {"start": True}), (1, 1))


if __name__ == "__main__":
    unittest.main()
